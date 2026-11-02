from __future__ import annotations

import hashlib
import json


SCALE_OPTIONS = (
    (1, "完全不同意"),
    (2, ""),
    (3, ""),
    (4, "中立"),
    (5, ""),
    (6, ""),
    (7, "完全同意"),
)

PRE_RESULT_INSTRUMENT_ID = "APPENDIX-A5-PRE-RESULT-EXPERIENCE"
PRE_RESULT_INSTRUMENT_VERSION = "appendix-a5-pre-result-experience-zh-v1"
PRE_RESULT_TITLE = "两种体验方式的感受"
PRE_RESULT_INSTRUCTIONS = (
    "在查看任何个人结果之前，请分别评价刚才的“虚拟岛屿互动”和“人格问卷”两种方式。"
    "没有正确或错误答案；如不愿回答，可跳过任何一题。"
)
PRE_RESULT_FORMATS = (
    ("island", "虚拟岛屿互动"),
    ("questionnaire", "人格问卷"),
)
PRE_RESULT_ITEMS = (
    (1, "这种方式让我能够自然地表达或呈现自己。"),
    (2, "完成这种方式时，我感到投入。"),
    (3, "完成这种方式让我感到负担较重。"),
    (4, "对于这种方式要求或记录的信息，我在隐私方面感到舒适。"),
    (5, "我觉得自己能够控制在这种方式中提供多少信息以及如何回应。"),
    (6, "如果将来有类似研究，我愿意再次使用这种方式。"),
)

POST_RESULT_INSTRUMENT_ID = "APPENDIX-A6-POST-RESULT-EVALUATION"
POST_RESULT_INSTRUMENT_VERSION = "appendix-a6-post-result-evaluation-zh-v1"
POST_RESULT_TITLE = "对刚才结果摘要的评价"
POST_RESULT_INSTRUCTIONS = "请评价您刚刚看到的结果摘要。如不愿回答，可跳过任何一题。"
POST_RESULT_ITEMS = (
    (1, "这份结果摘要表达清楚，容易理解。"),
    (2, "我能够理解这份结果大致是如何产生的。"),
    (3, "我信任这份结果的生成过程及其呈现方式。"),
    (4, "总体而言，这份结果与我对自己的认识相符。"),
)


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
    ).hexdigest()


PRE_RESULT_INSTRUMENT_SHA256 = _sha(
    {
        "instrument_id": PRE_RESULT_INSTRUMENT_ID,
        "version": PRE_RESULT_INSTRUMENT_VERSION,
        "language": "zh-CN",
        "title": PRE_RESULT_TITLE,
        "instructions": PRE_RESULT_INSTRUCTIONS,
        "formats": PRE_RESULT_FORMATS,
        "scale_options": SCALE_OPTIONS,
        "items": PRE_RESULT_ITEMS,
    }
)
POST_RESULT_INSTRUMENT_SHA256 = _sha(
    {
        "instrument_id": POST_RESULT_INSTRUMENT_ID,
        "version": POST_RESULT_INSTRUMENT_VERSION,
        "language": "zh-CN",
        "title": POST_RESULT_TITLE,
        "instructions": POST_RESULT_INSTRUCTIONS,
        "scale_options": SCALE_OPTIONS,
        "items": POST_RESULT_ITEMS,
    }
)


def _scale_payload() -> list[dict[str, object]]:
    return [{"value": value, "label": label} for value, label in SCALE_OPTIONS]


def pre_result_instrument_payload() -> dict[str, object]:
    return {
        "instrument_id": PRE_RESULT_INSTRUMENT_ID,
        "instrument_version": PRE_RESULT_INSTRUMENT_VERSION,
        "instrument_sha256": PRE_RESULT_INSTRUMENT_SHA256,
        "language": "zh-CN",
        "title": PRE_RESULT_TITLE,
        "instructions": PRE_RESULT_INSTRUCTIONS,
        "scale_options": _scale_payload(),
        "formats": [
            {"format_id": format_id, "label": label}
            for format_id, label in PRE_RESULT_FORMATS
        ],
        "items": [
            {"number": item_number, "text": text}
            for item_number, text in PRE_RESULT_ITEMS
        ],
        "all_items_optional": True,
        "explicit_skip_required": True,
    }


def post_result_instrument_payload() -> dict[str, object]:
    return {
        "instrument_id": POST_RESULT_INSTRUMENT_ID,
        "instrument_version": POST_RESULT_INSTRUMENT_VERSION,
        "instrument_sha256": POST_RESULT_INSTRUMENT_SHA256,
        "language": "zh-CN",
        "title": POST_RESULT_TITLE,
        "instructions": POST_RESULT_INSTRUCTIONS,
        "scale_options": _scale_payload(),
        "items": [
            {"number": item_number, "text": text}
            for item_number, text in POST_RESULT_ITEMS
        ],
        "all_items_optional": True,
        "explicit_skip_required": True,
    }
