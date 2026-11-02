"""Provider-neutral resident decision schemas."""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
import json

from world.specs import WorldSpecValidationError

DECISION_TYPES = ("atomic_action", "stage_action", "invitation_response", "reschedule", "event_preference", "dialogue", "invitation_expression", "record_expression")
PROMPT_VERSION = "modular-decision-prompt-v2"
OUTPUT_VERSION = "modular-decision-output-v1"
GATEWAY_VERSION = "modular-decision-gateway-v1"


@dataclass(frozen=True)
class DecisionPolicy:
    policy_version: str = "modular-llm-policy-v1"
    enabled: bool = False
    decision_types: tuple[str, ...] = DECISION_TYPES
    timeout_ms: int = 3000
    max_retries: int = 1
    max_calls_per_day: int = 32
    max_calls_per_session: int = 256
    max_units_per_day: int = 131072
    max_units_per_session: int = 1048576
    max_prompt_units: int = 8192
    max_output_units: int = 1024

    @classmethod
    def parse(cls, value: Mapping | None = None):
        if value is None:
            return cls()
        fields = set(cls.__dataclass_fields__)
        if not isinstance(value, Mapping) or set(value) != fields:
            raise WorldSpecValidationError("Unknown or missing LLM policy field.")
        if value["policy_version"] != cls().policy_version or type(value["enabled"]) is not bool:
            raise WorldSpecValidationError("Invalid LLM policy version or enable flag.")
        types = value["decision_types"]
        if not isinstance(types, (list, tuple)) or not types or len(set(types)) != len(types) or set(types) - set(DECISION_TYPES):
            raise WorldSpecValidationError("Unknown or repeated decision type.")
        limits = {"timeout_ms": (10, 20000), "max_retries": (0, 1), "max_calls_per_day": (1, 64),
                  "max_calls_per_session": (1, 512), "max_units_per_day": (1024, 1048576),
                  "max_units_per_session": (1024, 8388608), "max_prompt_units": (512, 32768), "max_output_units": (256, 4096)}
        for key, (low, high) in limits.items():
            if type(value[key]) is not int or not low <= value[key] <= high:
                raise WorldSpecValidationError(f"Invalid LLM policy limit: {key}.")
        if value["max_calls_per_day"] > value["max_calls_per_session"] or value["max_units_per_day"] > value["max_units_per_session"]:
            raise WorldSpecValidationError("Daily LLM limits exceed Session limits.")
        return cls(**{**value, "decision_types": tuple(types)})


def output_schema(snapshot_id: str, candidates: list[dict], expressions: list[str], facts: list[str]) -> dict:
    return {"type": "object", "additionalProperties": False,
            "required": ["schema_version", "snapshot_id", "candidate_id", "expression_id", "fact_refs"],
            "properties": {"schema_version": {"const": OUTPUT_VERSION}, "snapshot_id": {"const": snapshot_id},
                           "candidate_id": {"enum": [c["candidate_id"] for c in candidates]},
                           "expression_id": {"enum": expressions},
                           "fact_refs": {"type": "array", "maxItems": 16 if facts else 0, "uniqueItems": True,
                                         "items": {"type": "string", "enum": facts} if facts else {"type": "string"}}}}


class InvalidDecision(ValueError):
    pass


def validate_output(raw: str, packet: dict, max_output_units: int) -> dict:
    if not isinstance(raw, str) or not raw.strip():
        raise InvalidDecision("empty_output")
    try:
        output_units = len(raw.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise InvalidDecision("invalid_encoding") from exc
    if output_units > max_output_units:
        raise InvalidDecision("output_limit")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise InvalidDecision("duplicate_json_field")
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=unique)
    except (ValueError, RecursionError) as exc:
        if isinstance(exc, InvalidDecision):
            raise
        raise InvalidDecision("invalid_json") from exc
    if not isinstance(value, dict) or set(value) != {"schema_version", "snapshot_id", "candidate_id", "expression_id", "fact_refs"}:
        raise InvalidDecision("invalid_schema")
    if value["schema_version"] != OUTPUT_VERSION or value["snapshot_id"] != packet["snapshot_id"]:
        raise InvalidDecision("stale_output")
    if not isinstance(value["candidate_id"], str) or value["candidate_id"] not in {c["candidate_id"] for c in packet["candidates"]}:
        raise InvalidDecision("unknown_candidate")
    if not isinstance(value["expression_id"], str) or value["expression_id"] not in packet["expressions"]:
        raise InvalidDecision("unknown_expression")
    refs = value["fact_refs"]
    if not isinstance(refs, list) or len(refs) > 16 or any(not isinstance(f, str) for f in refs) or len(set(refs)) != len(refs) or set(refs) - {f["fact_ref"] for f in packet["known_facts"]}:
        raise InvalidDecision("unknown_fact")
    chosen = next(c for c in packet["candidates"] if c["candidate_id"] == value["candidate_id"])
    if set(refs) - set(chosen["fact_refs"]):
        raise InvalidDecision("unrelated_fact")
    return value
