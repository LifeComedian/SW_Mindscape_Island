import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from statistics import median
from typing import Any


FEATURE_VERSION = "features-v0.2"

NEGATIVE_WORDS = {
    "sad",
    "tired",
    "empty",
    "hopeless",
    "lonely",
    "worthless",
    "exhausted",
    "meaningless",
    "numb",
    "anxious",
    "guilty",
    "lost",
}
POSITIVE_WORDS = {
    "good",
    "better",
    "happy",
    "hopeful",
    "proud",
    "grateful",
    "calm",
    "okay",
    "fine",
    "glad",
}
SELF_REFERENCES = {"i", "me", "my", "mine", "myself"}
CHINESE_NEGATIVE_TERMS = {
    "难过",
    "低落",
    "绝望",
    "空虚",
    "孤独",
    "孤单",
    "疲惫",
    "焦虑",
    "痛苦",
    "迷茫",
    "累",
}
CHINESE_POSITIVE_TERMS = {
    "开心",
    "高兴",
    "很好",
    "好多了",
    "有希望",
    "自豪",
    "感激",
    "平静",
}
CHINESE_SELF_REFERENCES = {"我自己", "我的", "自己", "我"}


@dataclass(frozen=True)
class SessionFeatures:
    feature_version: str
    calculated_at: str
    behavior_features: dict[str, Any]
    text_features: dict[str, Any]
    data_quality: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _event_type(interaction) -> str:
    return getattr(interaction, "event_type", None) or getattr(interaction, "action_type", "")


def _created_at(interaction) -> datetime | None:
    return getattr(interaction, "created_at", None) or getattr(interaction, "timestamp", None)


def _tokenize(text: str) -> list[str]:
    normalized = text.lower()
    english_words = re.findall(r"\b[a-zA-Z']+\b", normalized)
    chinese_characters = re.findall(r"[\u4e00-\u9fff]", normalized)
    return english_words + chinese_characters


def _metadata(interaction) -> dict[str, Any]:
    raw = getattr(interaction, "metadata_json", "{}") or "{}"
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def extract_session_features(session, interactions: list) -> SessionFeatures:
    ordered = sorted(
        interactions,
        key=lambda item: _created_at(item) or datetime.min,
    )
    event_counts = {
        "post_view": 0,
        "like": 0,
        "unlike": 0,
        "skip": 0,
        "comment": 0,
        "agent_reply": 0,
        "user_post": 0,
        "day_advance": 0,
        "finish_session": 0,
    }
    unique_agents = set()
    latencies = []
    user_comments = []
    missing_fields = []

    for item in ordered:
        event = _event_type(item)
        if event in event_counts:
            event_counts[event] += 1
        agent_id = getattr(item, "agent_id", None)
        if agent_id:
            unique_agents.add(agent_id)
        latency = getattr(item, "response_latency_ms", None)
        if isinstance(latency, int) and latency >= 0:
            latencies.append(latency)
        if event == "comment":
            content = (getattr(item, "content", "") or "").strip()
            if content:
                user_comments.append(content)
            else:
                missing_fields.append(f"comment:{getattr(item, 'id', 'unknown')}:empty_content")
        _metadata(item)

    post_view_count = event_counts["post_view"]
    comment_count = event_counts["comment"]
    interaction_count = len(ordered)
    session_duration = _session_duration_seconds(session, ordered)

    behavior_features = {
        "post_view_count": post_view_count,
        "like_count": event_counts["like"],
        "unlike_count": event_counts["unlike"],
        "skip_count": event_counts["skip"],
        "comment_count": comment_count,
        "agent_reply_count": event_counts["agent_reply"],
        "user_post_count": event_counts["user_post"],
        "unique_agents_interacted": len(unique_agents),
        "engagement_rate": _safe_ratio(event_counts["like"] + comment_count, post_view_count),
        "skip_rate": _safe_ratio(event_counts["skip"], post_view_count),
        "comment_rate": _safe_ratio(comment_count, post_view_count),
        "average_response_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0,
        "median_response_latency_ms": round(float(median(latencies)), 2) if latencies else 0,
        "session_duration_seconds": session_duration,
    }

    text_features = _extract_text_features(user_comments)
    warnings = []
    if post_view_count == 0:
        warnings.append("No post_view events were recorded.")
    if comment_count == 0:
        warnings.append("No user comments were recorded.")

    data_quality = {
        "interaction_count": interaction_count,
        "comment_count": comment_count,
        "has_sufficient_data": interaction_count >= 1 and post_view_count >= 1 and comment_count >= 1,
        "missing_fields": missing_fields,
        "warnings": warnings,
    }

    return SessionFeatures(
        feature_version=FEATURE_VERSION,
        calculated_at=datetime.utcnow().isoformat() + "Z",
        behavior_features=behavior_features,
        text_features=text_features,
        data_quality=data_quality,
    )


def _session_duration_seconds(session, interactions: list) -> int:
    started_at = getattr(session, "started_at", None) or getattr(session, "created_at", None)
    ended_at = getattr(session, "ended_at", None)
    if ended_at is None and interactions:
        ended_at = _created_at(interactions[-1])
    if started_at is None or ended_at is None:
        return 0
    return max(int((ended_at - started_at).total_seconds()), 0)


def _extract_text_features(comments: list[str]) -> dict[str, Any]:
    tokens_by_comment = [_tokenize(comment) for comment in comments]
    words = [word for tokens in tokens_by_comment for word in tokens]
    word_count = len(words)
    unique_word_count = len(set(words))
    negative_count = (
        sum(1 for word in words if word in NEGATIVE_WORDS)
        + _count_chinese_terms(comments, CHINESE_NEGATIVE_TERMS)
    )
    positive_count = (
        sum(1 for word in words if word in POSITIVE_WORDS)
        + _count_chinese_terms(comments, CHINESE_POSITIVE_TERMS)
    )
    self_reference_count = (
        sum(1 for word in words if word in SELF_REFERENCES)
        + _count_chinese_terms(comments, CHINESE_SELF_REFERENCES)
    )
    question_count = sum(
        comment.count("?") + comment.count("？")
        for comment in comments
    )

    return {
        "comment_total_word_count": word_count,
        "average_comment_length_words": round(word_count / max(len(comments), 1), 2),
        "negative_word_count": negative_count,
        "negative_word_ratio": _safe_ratio(negative_count, word_count),
        "positive_word_count": positive_count,
        "positive_word_ratio": _safe_ratio(positive_count, word_count),
        "self_reference_count": self_reference_count,
        "self_reference_ratio": _safe_ratio(self_reference_count, word_count),
        "question_count": question_count,
        "lexical_diversity": _safe_ratio(unique_word_count, word_count),
    }


def _count_chinese_terms(comments: list[str], terms: set[str]) -> int:
    if not comments or not terms:
        return 0
    pattern = "|".join(re.escape(term) for term in sorted(terms, key=len, reverse=True))
    return sum(len(re.findall(pattern, comment)) for comment in comments)


def _safe_ratio(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 0
    return round(float(numerator) / float(denominator), 4)
