from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping


INSTRUMENT_ID = "BFI-2-60"
INSTRUMENT_LANGUAGE = "zh-CN"
INSTRUMENT_VERSION = "bfi2-zh-cn-60-zhang-2022-appendix-a4-v1"
SCORING_VERSION = "bfi2-60-domain-facet-mean-reverse-6-minus-v1"
REPORT_TEMPLATE_VERSION = "bfi2-neutral-continuous-report-zh-v1"
INSTRUMENT_SOURCE = (
    "Zhang et al. (2022), The Big Five Inventory-2 in China: "
    "A Comprehensive Psychometric Evaluation in Four Diverse Samples, "
    "Assessment, 29(6), 1262–1284. Chinese wording reproduced in approved Appendix A4."
)
INSTRUMENT_TITLE = "大五人格问卷第二版（BFI-2）"
INSTRUCTIONS = (
    "下面是一些关于个人特征的描述，有些可能适用于你，有些可能不适用于你。"
    "比如，你是否同意“我是一个喜欢与他人待在一起的人”？"
    "请在每个句子中选择一个数字，以表明你同意或不同意这个描述。"
)
ITEM_STEM = "我是一个……的人"
SCALE_OPTIONS = (
    (1, "非常不同意"),
    (2, "不太同意"),
    (3, "态度中立"),
    (4, "比较同意"),
    (5, "非常同意"),
)


@dataclass(frozen=True, slots=True)
class BFI2Item:
    number: int
    text: str


ITEMS = (
    BFI2Item(1, "性格外向，喜欢交际"),
    BFI2Item(2, "心肠柔软，有同情心"),
    BFI2Item(3, "缺乏条理"),
    BFI2Item(4, "从容，善于处理压力"),
    BFI2Item(5, "对艺术没有什么兴趣"),
    BFI2Item(6, "性格坚定自信，敢于表达自己的观点"),
    BFI2Item(7, "为人恭谦，尊重他人"),
    BFI2Item(8, "比较懒"),
    BFI2Item(9, "经历挫折后仍能保持积极心态"),
    BFI2Item(10, "对许多不同的事物都感兴趣"),
    BFI2Item(11, "很少觉得兴奋或者特别想要（做）什么"),
    BFI2Item(12, "常常挑别人的毛病"),
    BFI2Item(13, "可信赖的，可靠的"),
    BFI2Item(14, "喜怒无常，情绪起伏较多"),
    BFI2Item(15, "善于创造，能找到聪明的方法来做事"),
    BFI2Item(16, "比较安静"),
    BFI2Item(17, "对他人没有什么同情心"),
    BFI2Item(18, "做事有计划有条理"),
    BFI2Item(19, "容易紧张"),
    BFI2Item(20, "着迷于艺术、音乐或文学"),
    BFI2Item(21, "常常处于主导地位，像个领导一样"),
    BFI2Item(22, "常与他人意见不和"),
    BFI2Item(23, "很难开始行动起来去完成一项任务"),
    BFI2Item(24, "觉得有安全感，对自己满意"),
    BFI2Item(25, "不喜欢知识性或者哲学性强的讨论"),
    BFI2Item(26, "不如别人有活力"),
    BFI2Item(27, "宽宏大量"),
    BFI2Item(28, "有时比较没有责任心"),
    BFI2Item(29, "情绪稳定，不易生气"),
    BFI2Item(30, "几乎没有什么创造性"),
    BFI2Item(31, "有时会害羞，比较内向"),
    BFI2Item(32, "乐于助人，待人无私"),
    BFI2Item(33, "习惯让事物保持整洁有序"),
    BFI2Item(34, "时常忧心忡忡，担心很多事情"),
    BFI2Item(35, "重视艺术与审美"),
    BFI2Item(36, "感觉自己很难对他人产生影响"),
    BFI2Item(37, "有时对人比较粗鲁"),
    BFI2Item(38, "有效率，做事有始有终"),
    BFI2Item(39, "时常觉得悲伤"),
    BFI2Item(40, "思想深刻"),
    BFI2Item(41, "精力充沛"),
    BFI2Item(42, "不相信别人，怀疑别人的意图"),
    BFI2Item(43, "可靠的，总是值得他人信赖"),
    BFI2Item(44, "能够控制自己的情绪"),
    BFI2Item(45, "缺乏想象力"),
    BFI2Item(46, "爱说话，健谈"),
    BFI2Item(47, "有时对人冷淡，漠不关心"),
    BFI2Item(48, "乱糟糟的，不爱收拾"),
    BFI2Item(49, "很少觉得焦虑或者害怕"),
    BFI2Item(50, "觉得诗歌、戏剧很无聊"),
    BFI2Item(51, "更喜欢让别人来领头负责"),
    BFI2Item(52, "待人谦逊礼让"),
    BFI2Item(53, "有恒心，能坚持把事情做完"),
    BFI2Item(54, "时常觉得郁郁寡欢"),
    BFI2Item(55, "对抽象的概念和想法没什么兴趣"),
    BFI2Item(56, "充满热情"),
    BFI2Item(57, "把人往最好的方面想"),
    BFI2Item(58, "有时候会做出一些不负责任的行为"),
    BFI2Item(59, "情绪多变，容易愤怒"),
    BFI2Item(60, "有创意，能想出新点子"),
)


DOMAIN_KEYS: dict[str, tuple[int, ...]] = {
    "extraversion": (1, 6, -11, -16, 21, -26, -31, -36, 41, 46, -51, 56),
    "agreeableness": (2, 7, -12, -17, -22, 27, 32, -37, -42, -47, 52, 57),
    "conscientiousness": (-3, -8, 13, 18, -23, -28, 33, 38, 43, -48, 53, -58),
    "negative_emotionality": (-4, -9, 14, 19, -24, -29, 34, 39, -44, -49, 54, 59),
    "open_mindedness": (-5, 10, 15, 20, -25, -30, 35, 40, -45, -50, -55, 60),
}

FACET_KEYS: dict[str, tuple[int, ...]] = {
    "sociability": (1, -16, -31, 46),
    "assertiveness": (6, 21, -36, -51),
    "energy_level": (-11, -26, 41, 56),
    "compassion": (2, -17, 32, -47),
    "respectfulness": (7, -22, -37, 52),
    "trust": (-12, 27, -42, 57),
    "organization": (-3, 18, 33, -48),
    "productiveness": (-8, -23, 38, 53),
    "responsibility": (13, -28, 43, -58),
    "anxiety": (-4, 19, 34, -49),
    "depression": (-9, -24, 39, 54),
    "emotional_volatility": (14, -29, -44, 59),
    "intellectual_curiosity": (10, -25, 40, -55),
    "aesthetic_sensitivity": (-5, 20, 35, -50),
    "creative_imagination": (15, -30, -45, 60),
}

DOMAIN_LABELS_ZH = {
    "extraversion": "外向性",
    "agreeableness": "宜人性",
    "conscientiousness": "尽责性",
    "negative_emotionality": "负性情绪",
    "open_mindedness": "开放性",
}

FACET_LABELS_ZH = {
    "sociability": "社交",
    "assertiveness": "果断",
    "energy_level": "活力",
    "compassion": "同情",
    "respectfulness": "谦恭",
    "trust": "信任",
    "organization": "条理",
    "productiveness": "效率",
    "responsibility": "负责",
    "anxiety": "焦虑",
    "depression": "抑郁",
    "emotional_volatility": "易变",
    "intellectual_curiosity": "好奇",
    "aesthetic_sensitivity": "审美",
    "creative_imagination": "想象",
}

REVERSED_ITEM_NUMBERS = frozenset(
    abs(item) for key in DOMAIN_KEYS.values() for item in key if item < 0
)

_INSTRUMENT_MATERIAL = {
    "instrument_id": INSTRUMENT_ID,
    "language": INSTRUMENT_LANGUAGE,
    "version": INSTRUMENT_VERSION,
    "title": INSTRUMENT_TITLE,
    "instructions": INSTRUCTIONS,
    "item_stem": ITEM_STEM,
    "scale_options": SCALE_OPTIONS,
    "items": [(item.number, item.text) for item in ITEMS],
    "source": INSTRUMENT_SOURCE,
}
INSTRUMENT_SHA256 = hashlib.sha256(
    json.dumps(
        _INSTRUMENT_MATERIAL,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
).hexdigest()


@dataclass(frozen=True, slots=True)
class BFI2ScoreResult:
    transformed_item_scores: dict[int, int]
    domain_scores: dict[str, float]
    facet_scores: dict[str, float]


def _validate_contract() -> None:
    expected = set(range(1, 61))
    if [item.number for item in ITEMS] != list(range(1, 61)):
        raise RuntimeError("BFI-2 item order must be exactly 1 through 60.")
    domain_items = [abs(item) for key in DOMAIN_KEYS.values() for item in key]
    facet_items = [abs(item) for key in FACET_KEYS.values() for item in key]
    if set(domain_items) != expected or len(domain_items) != 60:
        raise RuntimeError("BFI-2 domain scoring key must cover every item once.")
    if set(facet_items) != expected or len(facet_items) != 60:
        raise RuntimeError("BFI-2 facet scoring key must cover every item once.")
    domain_direction = {abs(item): item < 0 for key in DOMAIN_KEYS.values() for item in key}
    facet_direction = {abs(item): item < 0 for key in FACET_KEYS.values() for item in key}
    if domain_direction != facet_direction:
        raise RuntimeError("BFI-2 domain and facet reversal keys disagree.")


_validate_contract()


def validate_answers(answers: Mapping[int, int]) -> dict[int, int]:
    normalized = dict(answers)
    if set(normalized) != set(range(1, 61)):
        raise ValueError("Exactly one answer is required for each item 1 through 60.")
    if any(isinstance(value, bool) or not isinstance(value, int) or value not in range(1, 6) for value in normalized.values()):
        raise ValueError("Every BFI-2 answer must be an integer from 1 through 5.")
    return dict(sorted(normalized.items()))


def score_bfi2(answers: Mapping[int, int]) -> BFI2ScoreResult:
    normalized = validate_answers(answers)
    transformed = {
        item_number: 6 - value if item_number in REVERSED_ITEM_NUMBERS else value
        for item_number, value in normalized.items()
    }

    def means(keys: Mapping[str, tuple[int, ...]]) -> dict[str, float]:
        return {
            name: round(sum(transformed[abs(item)] for item in item_keys) / len(item_keys), 4)
            for name, item_keys in keys.items()
        }

    return BFI2ScoreResult(
        transformed_item_scores=transformed,
        domain_scores=means(DOMAIN_KEYS),
        facet_scores=means(FACET_KEYS),
    )


def render_neutral_report(result: BFI2ScoreResult) -> str:
    lines = [
        "标准化问卷结果",
        "本结果依据固定版本的 BFI-2 计分规则生成，分数范围为 1.00–5.00，并按连续维度呈现。",
    ]
    for domain_id, label in DOMAIN_LABELS_ZH.items():
        lines.append(f"{label}：{result.domain_scores[domain_id]:.2f} / 5.00")
    lines.extend(
        [
            "这些分数描述本次问卷回答在五个连续维度上的位置，不代表好坏，也不使用人群常模、百分位或临床阈值。",
            "这是一份非诊断性研究结果，不应用于医疗、学业、就业、纪律、资格或其他重要决定。",
        ]
    )
    return "\n".join(lines)


def participant_instrument_payload() -> dict[str, object]:
    return {
        "instrument_id": INSTRUMENT_ID,
        "instrument_version": INSTRUMENT_VERSION,
        "instrument_sha256": INSTRUMENT_SHA256,
        "language": INSTRUMENT_LANGUAGE,
        "title": INSTRUMENT_TITLE,
        "instructions": INSTRUCTIONS,
        "item_stem": ITEM_STEM,
        "scale_options": [
            {"value": value, "label": label} for value, label in SCALE_OPTIONS
        ],
        "items": [{"number": item.number, "text": item.text} for item in ITEMS],
        "source_notice": (
            "中文版措辞来源：Zhang et al. (2022) 论文附录；"
            "BFI-2 版权归 Christopher J. Soto 与 Oliver P. John，供非商业研究使用。"
        ),
    }

