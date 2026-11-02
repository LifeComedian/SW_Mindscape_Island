crisis_keywords = [
    "kill myself",
    "suicide",
    "end my life",
    "hurt myself",
]


def detect_crisis_language(texts: list[str]) -> bool:
    combined_text = " ".join(texts).lower()
    return any(keyword in combined_text for keyword in crisis_keywords)


def build_score_summary(risk_level: str) -> str:
    disclaimer = (
        "This is a research prototype and not a medical diagnosis, treatment tool, "
        "or crisis service."
    )

    if risk_level == "low":
        signal_text = "This session shows relatively low possible emotional distress signals."
    elif risk_level == "moderate":
        signal_text = "This session shows some possible emotional distress signals."
    else:
        signal_text = "This session shows stronger possible emotional distress signals."

    return f"{signal_text} {disclaimer}"


def build_crisis_warning() -> str:
    return (
        "This prototype detected language that may indicate immediate risk. "
        "If you may be in danger, contact local emergency services or a trusted person nearby. "
        "This system cannot provide emergency support or medical diagnosis."
    )
