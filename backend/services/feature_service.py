import re


negative_words = [
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
]

self_refs = ["i", "me", "my", "myself"]


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\b[a-zA-Z']+\b", text.lower())


def extract_text_features(texts: list[str]) -> dict:
    combined_text = " ".join(texts)
    words = _tokenize(combined_text)

    word_count = len(words)
    negative_count = sum(1 for word in words if word in negative_words)
    self_ref_count = sum(1 for word in words if word in self_refs)
    avg_response_length = word_count / max(len(texts), 1)

    return {
        "word_count": word_count,
        "negative_count": negative_count,
        "self_ref_count": self_ref_count,
        "avg_response_length": round(avg_response_length, 2),
    }


def extract_behavior_features(interactions: list) -> dict:
    total_interactions = len(interactions)
    comment_count = sum(1 for item in interactions if item.action_type == "comment")
    like_count = sum(1 for item in interactions if item.action_type == "like")
    skip_count = sum(1 for item in interactions if item.action_type == "skip")

    engagement_score = (comment_count + like_count) / max(total_interactions, 1)
    skip_rate = skip_count / max(total_interactions, 1)

    return {
        "total_interactions": total_interactions,
        "comment_count": comment_count,
        "like_count": like_count,
        "skip_count": skip_count,
        "engagement_score": round(engagement_score, 2),
        "skip_rate": round(skip_rate, 2),
    }
