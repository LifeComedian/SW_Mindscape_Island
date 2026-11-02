from dataclasses import dataclass


SAFETY_KEYWORDS = [
    "kill myself",
    "suicide",
    "end my life",
    "hurt myself",
    "self harm",
    "self-harm",
    "want to die",
    "自杀",
    "不想活",
    "结束生命",
    "伤害自己",
    "自残",
    "想死",
]

SAFE_REPLY = (
    "I'm sorry you're dealing with something this heavy. Please contact a trusted person nearby "
    "or local emergency services if you may be in danger. This prototype cannot provide emergency "
    "support or medical advice."
)
SAFE_REPLY_ZH_CN = (
    "听起来你正在承受非常沉重的事情。如果你可能正处于危险中，请立即联系身边可信任的"
    "人或当地紧急服务。本原型无法提供紧急援助或医疗建议。"
)


@dataclass(frozen=True)
class SafetyCheck:
    safety_flag: bool
    category: str
    reply_text: str | None = None


def check_user_comment_safety(text: str, language: str = "en") -> SafetyCheck:
    normalized = text.lower()
    if any(keyword in normalized for keyword in SAFETY_KEYWORDS):
        return SafetyCheck(
            safety_flag=True,
            category="safety_sensitive",
            reply_text=SAFE_REPLY_ZH_CN if language == "zh-CN" else SAFE_REPLY,
        )
    return SafetyCheck(safety_flag=False, category="ordinary")
