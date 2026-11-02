"""Chat Completions transport with deadlines and concurrency limits."""
import asyncio
import json
import ssl
import time
import threading
import os
from collections import deque
from functools import lru_cache
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import httpx
import certifi
from config import settings


class TransportError(RuntimeError):
    """Only stable, nonsecret error codes cross the provider boundary."""


def _foreground_limit():
    value=int(os.environ.get('LLM_FOREGROUND_CONCURRENCY','2'))
    if not 1 <= value <= 16:
        raise ValueError('LLM_FOREGROUND_CONCURRENCY must be between 1 and 16')
    return value

_global_slots = {"foreground": threading.BoundedSemaphore(_foreground_limit()), "background": threading.BoundedSemaphore(2)}
_queue_slots = {"foreground": threading.BoundedSemaphore(32), "background": threading.BoundedSemaphore(16)}
_waiting = {"foreground": deque(), "background": deque()}
_waiting_lock = threading.Lock()
QWEN_HOSTS = frozenset({"dashscope.aliyuncs.com", "maas.qianwenaiapi.com"})


@lru_cache(maxsize=4)
def _tls_context(cafile):
    # Immutable after creation; reuse verified CA setup, never disable TLS.
    return ssl.create_default_context(cafile=cafile)


@asynccontextmanager
async def provider_slot(purpose):
    """Bounded across Sessions, worker threads AND event loops (single API worker)."""
    if purpose not in _global_slots:
        raise TransportError("invalid_request_purpose")
    if not _queue_slots[purpose].acquire(blocking=False):
        raise TransportError("provider_queue_full")
    acquired = False
    ticket = object()
    with _waiting_lock:
        _waiting[purpose].append(ticket)
    try:
        while not acquired:
            with _waiting_lock:
                if _waiting[purpose][0] is ticket:
                    acquired = _global_slots[purpose].acquire(blocking=False)
                    if acquired:
                        _waiting[purpose].popleft()
            if not acquired:
                await asyncio.sleep(0.02)
        yield
    finally:
        with _waiting_lock:
            if ticket in _waiting[purpose]:
                _waiting[purpose].remove(ticket)
        if acquired:
            _global_slots[purpose].release()
        _queue_slots[purpose].release()


def safe_configuration(config=settings):
    return {"provider": config.llm_provider, "model": config.llm_model,
            "host": urlsplit(config.resolved_llm_base_url or "https://api.openai.com/v1").hostname,
            "key_present": bool(config.resolved_llm_api_key), "network_mode": config.llm_network_mode,
            "proxy_configured": bool(config.llm_proxy_url), "tls_verification": True,
            "deadline_seconds": config.llm_total_deadline_seconds, "retries": config.llm_transport_retries}


def classify_status(status):
    if status in (401, 403):
        return "authentication_or_region"
    if status in (400, 404, 422):
        return "endpoint_model_or_parameters"
    if status == 429:
        return "rate_or_quota_limit"
    return "provider_http_failure"


class ChatTransport:
    @classmethod
    def for_dialogue(cls, config=settings):
        from dataclasses import replace
        if config.llm_provider in ('qwen','dashscope') and config.llm_model.startswith('qwen3.8-'):
            config=replace(config,llm_thinking='off',llm_reasoning_effort='',
                           llm_max_output_tokens=max(700,config.llm_max_output_tokens))
        return cls(config)

    def __init__(self, config=settings, *, transport=None):
        self.config, self.transport = config, transport
        self.last_metrics = {}

    async def generate(self, messages, *, purpose="foreground", schema=None, max_output_tokens=None, retry=True):
        self.last_metrics = {"purpose": purpose, "attempts": 0, "phase": "configuration"}
        from agents.chinese_style import style_messages
        messages = style_messages(messages)
        c = self.config
        if not c.resolved_llm_api_key or not c.llm_model:
            raise TransportError("provider_not_configured")
        if c.llm_network_mode not in ("direct", "proxy") or (c.llm_network_mode == "proxy" and not c.llm_proxy_url):
            raise TransportError("invalid_network_configuration")
        if c.llm_transport_retries not in (0, 1) or not 0 < c.llm_total_deadline_seconds <= 120:
            raise TransportError("invalid_transport_limits")
        base = (c.resolved_llm_base_url or "https://api.openai.com/v1").rstrip("/")
        parsed = urlsplit(base)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise TransportError("invalid_api_host")
        if c.llm_provider in ("qwen", "dashscope") and self.transport is None and (parsed.hostname not in QWEN_HOSTS or parsed.port not in (None, 443)):
            raise TransportError("unapproved_qwen_host")
        body = {"model": c.llm_model, "messages": messages,
                "max_tokens": min(max_output_tokens or c.llm_max_output_tokens, c.llm_max_output_tokens)}
        output_limit = body["max_tokens"]
        if not 1 <= output_limit <= 4096 or len(json.dumps(messages, ensure_ascii=False).encode("utf-8")) > c.llm_max_input_bytes:
            raise TransportError("input_or_output_limit")
        qwen38 = c.llm_provider in ("qwen", "dashscope") and c.llm_model.startswith("qwen3.8-")
        if qwen38:
            # The platform's max_tokens excludes reasoning. Bound the entire
            # generated completion so background budgets also cover thinking.
            body["max_completion_tokens"] = body.pop("max_tokens")
        if c.llm_reasoning_effort:
            if not qwen38 or c.llm_reasoning_effort not in ("low", "medium", "xhigh") or c.llm_thinking == "off":
                raise TransportError("invalid_reasoning_effort")
            body["reasoning_effort"] = c.llm_reasoning_effort
        if c.llm_thinking not in ("auto", "on", "off"):
            raise TransportError("invalid_thinking_mode")
        if c.llm_thinking != "auto":
            if c.llm_provider not in ("qwen", "dashscope"):
                raise TransportError("thinking_capability_not_configured")
            body["enable_thinking"] = c.llm_thinking == "on"
        if schema is not None:
            if c.llm_structured_mode == "json_schema":
                body["response_format"] = {"type": "json_schema", "json_schema": {"name": "resident_decision", "strict": True, "schema": schema}}
            elif c.llm_structured_mode == "json_object":
                body["response_format"] = {"type": "json_object"}
            else:
                raise TransportError("invalid_structured_mode")
        start = time.perf_counter()
        metrics = {"purpose": purpose, "attempts": 0, "host": parsed.hostname, "phase": "queue"}
        self.last_metrics = metrics
        verify = _tls_context(c.llm_ca_bundle or certifi.where())
        metrics['tls_setup_ms'] = int((time.perf_counter() - start) * 1000)
        try:
            async with asyncio.timeout(c.llm_total_deadline_seconds):
                async with provider_slot(purpose):
                    metrics["queue_ms"] = int((time.perf_counter() - start) * 1000)
                    metrics["phase"] = "request_headers"
                    async with httpx.AsyncClient(trust_env=False, verify=verify,
                        proxy=c.llm_proxy_url if c.llm_network_mode == "proxy" else None,
                        transport=self.transport, timeout=httpx.Timeout(c.llm_timeout_seconds, connect=c.llm_connect_timeout_seconds)) as client:
                        for attempt in range((c.llm_transport_retries if retry else 0) + 1):
                            metrics["attempts"] += 1
                            try:
                                async with client.stream("POST", base + "/chat/completions", json=body,
                                    headers={"Authorization": "Bearer " + c.resolved_llm_api_key}) as response:
                                    metrics["headers_ms"] = int((time.perf_counter() - start) * 1000)
                                    metrics["http_status"] = response.status_code
                                    metrics["phase"] = "response_body"
                                    if response.status_code >= 400:
                                        if response.status_code in (429, 500, 502, 503, 504) and attempt < (c.llm_transport_retries if retry else 0):
                                            await asyncio.sleep(0.1 * (attempt + 1))
                                            continue
                                        raise TransportError(classify_status(response.status_code))
                                    chunks, size = [], 0
                                    async for chunk in response.aiter_bytes():
                                        size += len(chunk)
                                        if size > max(32768, output_limit * 32):
                                            raise TransportError("response_size_limit")
                                        chunks.append(chunk)
                                    metrics["phase"] = "response_parse"
                                    try:
                                        data = json.loads(b"".join(chunks))
                                        text = data["choices"][0]["message"]["content"]
                                    except (ValueError, KeyError, IndexError, TypeError):
                                        raise TransportError("invalid_provider_response") from None
                                    usage = data.get("usage", {})
                                    if isinstance(usage, dict):
                                        metrics["usage"] = {k: v for k, v in usage.items() if k in ("prompt_tokens", "completion_tokens", "total_tokens") and type(v) is int and v >= 0}
                                        for source, field in (("prompt_tokens_details", "cached_tokens"), ("completion_tokens_details", "reasoning_tokens")):
                                            value = usage.get(source, {}).get(field) if isinstance(usage.get(source), dict) else None
                                            if type(value) is int and value >= 0:
                                                metrics["usage"][field] = value
                                    metrics["model"] = c.llm_model
                                    returned_model = data.get("model")
                                    if isinstance(returned_model, str) and len(returned_model) <= 120:
                                        metrics["returned_model"] = returned_model
                                    finish = data["choices"][0].get("finish_reason")
                                    metrics["finish_reason"] = finish if finish in ("stop", "length", "content_filter", "tool_calls") else "unknown"
                                    if finish == "length":
                                        raise TransportError("truncated_provider_response")
                                    if finish in ("content_filter", "tool_calls"):
                                        raise TransportError("unexpected_finish_reason")
                                    if not isinstance(text, str) or not text.strip():
                                        raise TransportError("empty_provider_response")
                                    if len(text.encode("utf-8")) > output_limit * 8:
                                        raise TransportError("output_size_limit")
                                    metrics["status"] = "success"
                                    metrics["phase"] = "output_check"
                                    from agents.output_safety import check_text
                                    return check_text(text.strip())
                            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                                metrics["error_class"] = type(exc).__name__
                                metrics["error_code"] = "network_or_tls_failure"
                                if attempt >= (c.llm_transport_retries if retry else 0):
                                    raise TransportError("network_or_tls_failure") from None
        except TimeoutError:
            metrics["error_code"] = "total_deadline"
            raise TransportError("total_deadline") from None
        except TransportError as exc:
            metrics["error_code"] = str(exc)
            raise
        except httpx.HTTPError:
            metrics["error_code"] = "network_or_tls_failure"
            raise TransportError("network_or_tls_failure") from None
        finally:
            metrics["total_ms"] = int((time.perf_counter() - start) * 1000)
            metrics.setdefault("status", "failed_or_cancelled")
