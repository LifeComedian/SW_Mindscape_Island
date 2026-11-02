from __future__ import annotations

import hashlib
import json


COMPARATIVE_INSTRUMENT_ID = "APPENDIX-A7-COMPARATIVE-FEEDBACK"
COMPARATIVE_INSTRUMENT_VERSION = "appendix-a7-comparative-feedback-zh-v1"
COMPARATIVE_TITLE = "两种方式的比较"
COMPARATIVE_INSTRUCTIONS = (
    "现在请比较“虚拟岛屿互动”和“人格问卷”两种方式。所有问题均可跳过。"
)
COMPARATIVE_OPTIONS = (
    ("island", "虚拟岛屿"),
    ("questionnaire", "人格问卷"),
    ("about_same", "差不多"),
    ("unsure", "不确定"),
)
COMPARATIVE_ITEMS = (
    (1, "哪种方式让您感觉更自然？"),
    (2, "哪种方式让您更投入？"),
    (3, "哪种方式的负担更小？"),
    (4, "哪种方式让您在隐私方面更舒适？"),
    (5, "哪种方式让您感觉更有控制感？"),
    (6, "哪种方式的结果更容易理解？"),
    (7, "哪种方式的结果更值得信任？"),
    (8, "哪种方式的结果更符合您对自己的认识？"),
    (9, "如果将来再次参加类似研究，您更愿意使用哪种方式？"),
    (10, "总体而言，您更偏好哪种方式？"),
)
OPEN_FEEDBACK_ITEMS = (
    (1, "请简要说明您总体偏好某一种方式，或认为两者差不多的原因。"),
    (2, "虚拟岛屿体验中，哪些内容让您更容易或更难自然地做出选择和表达自己？"),
    (3, "人格问卷中，哪些内容让您更容易或更难回答？"),
    (4, "两种方式中，是否有任何内容让您在隐私、被观察或被评价方面感到不舒服？如果愿意，请说明。"),
    (5, "您认为虚拟岛屿、结果解释或研究流程还可以如何改进？"),
    (6, "还有其他想告诉研究团队的内容吗？"),
)

DEBRIEF_VERSION = "appendix-a8-debriefing-statement-zh-v1"
DEBRIEF_TITLE = "研究结束说明"
DEBRIEF_PARAGRAPHS = (
    "感谢您完成本研究。本研究希望比较两种非临床人格相关研究形式：一是您在 MindScape Island 中的行为、选择和文字互动所形成的探索性研究估计；二是中文版大五人格问卷第二版（BFI-2）的标准化自我报告结果。研究团队还会比较您对两种形式的自然程度、投入感、负担、隐私舒适度、控制感、透明度、信任和使用意愿的评价。",
    "岛屿互动结果是在系统接收您的人格问卷答案之前，根据预先定义的编码语言、行为与选择特征生成并冻结的。人格问卷答案没有发送给岛上 AI 角色，也没有发送给 Qwen3.8-Max 用于对话或人格估计。两份结果以随机顺序显示，以减少先后顺序对体验评价的影响。",
    "岛屿互动结果仍处于探索阶段，不是经过验证的个体人格测验，也不是心理或医学诊断。任何结果都不代表固定身份，不应用于医疗、学业、就业、纪律、资格或其他重要决定。不同方法得出的结果可能并不一致，这并不意味着某一种结果必然正确。",
    "如果本研究使您感到不适，您可以停止查看结果或联系研究团队。您可以在完成研究后的14个自然日内，使用报名邮箱并提供研究编号，联系 researcher@example.invalid 申请删除可识别到您的游戏、问卷和反馈数据。研究团队会在收到符合时限的请求后7个自然日内完成处理。研究最后一名参与者完成研究后，联系信息和编号对应表将在不晚于21个自然日内删除；之后可能无法再定位并删除某一位参与者的数据。",
    "如对研究有疑问，请联系 Weitian Xue（researcher@example.invalid）或 Yucheng Jin（mentor@example.invalid）。如对参与者权利、投诉或研究团队未能解决的问题有疑问，请联系 Duke Kunshan University Institutional Review Board：ethics@example.invalid。",
)


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
    ).hexdigest()


COMPARATIVE_INSTRUMENT_SHA256 = _sha(
    {
        "instrument_id": COMPARATIVE_INSTRUMENT_ID,
        "version": COMPARATIVE_INSTRUMENT_VERSION,
        "language": "zh-CN",
        "title": COMPARATIVE_TITLE,
        "instructions": COMPARATIVE_INSTRUCTIONS,
        "options": COMPARATIVE_OPTIONS,
        "items": COMPARATIVE_ITEMS,
        "open_feedback_items": OPEN_FEEDBACK_ITEMS,
    }
)
DEBRIEF_SHA256 = _sha(
    {
        "version": DEBRIEF_VERSION,
        "language": "zh-CN",
        "title": DEBRIEF_TITLE,
        "paragraphs": DEBRIEF_PARAGRAPHS,
    }
)


def comparative_instrument_payload() -> dict[str, object]:
    return {
        "instrument_id": COMPARATIVE_INSTRUMENT_ID,
        "instrument_version": COMPARATIVE_INSTRUMENT_VERSION,
        "instrument_sha256": COMPARATIVE_INSTRUMENT_SHA256,
        "language": "zh-CN",
        "title": COMPARATIVE_TITLE,
        "instructions": COMPARATIVE_INSTRUCTIONS,
        "options": [
            {"value": value, "label": label} for value, label in COMPARATIVE_OPTIONS
        ],
        "items": [
            {"number": number, "text": text} for number, text in COMPARATIVE_ITEMS
        ],
        "open_feedback_title": "开放反馈（均可跳过）",
        "open_feedback_items": [
            {"number": number, "text": text} for number, text in OPEN_FEEDBACK_ITEMS
        ],
        "all_items_optional": True,
        "explicit_skip_required": True,
        "open_feedback_max_length": 2000,
    }


def debrief_payload() -> dict[str, object]:
    return {
        "debrief_version": DEBRIEF_VERSION,
        "debrief_sha256": DEBRIEF_SHA256,
        "language": "zh-CN",
        "title": DEBRIEF_TITLE,
        "paragraphs": list(DEBRIEF_PARAGRAPHS),
        "acknowledgement_label": "我已阅读研究结束说明",
    }
