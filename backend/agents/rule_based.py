import re
import time

from agents.base import AgentRequest, AgentResult
from agents.personas import get_persona
from agents.safety import check_user_comment_safety


NEGATIVE_TERMS = {"sad", "empty", "hopeless", "worthless", "lost", "numb", "anxious"}
POSITIVE_TERMS = {"good", "better", "fine", "happy", "hopeful", "proud", "grateful"}
TIRED_TERMS = {"tired", "exhausted", "burned", "burnt", "stress", "stressed", "overwhelmed"}
LONELY_TERMS = {"lonely", "alone", "isolated", "ignored", "left out"}
CHINESE_NEGATIVE_TERMS = {"难过", "低落", "绝望", "空虚", "麻木", "焦虑", "迷茫", "痛苦"}
CHINESE_POSITIVE_TERMS = {"开心", "高兴", "很好", "好多了", "有希望", "自豪", "感激", "平静"}
CHINESE_TIRED_TERMS = {"累", "疲惫", "筋疲力尽", "压力", "焦头烂额", "撑不住", "耗尽"}
CHINESE_LONELY_TERMS = {"孤独", "孤单", "一个人", "被忽视", "没人理解", "孤立"}


TEMPLATES = {
    "Supportive Agent": {
        "positive": "That sounds like a real bright spot. I'm glad you noticed it.",
        "negative": "That sounds difficult. I hope you can be gentle with yourself today.",
        "tired_or_stressed": "That kind of tired can be a lot. A small pause might still count.",
        "lonely_or_isolated": "Feeling alone around people can really hurt. I'm glad you said it here.",
        "question": "That's a thoughtful question. I wonder what would feel easiest to try first.",
        "neutral": "I hear you. Thanks for putting that into words.",
    },
    "Analytical Agent": {
        "positive": "That is useful data about what helped. What made that moment different?",
        "negative": "That sounds like a hard pattern. It may help to separate facts from assumptions.",
        "tired_or_stressed": "That sounds like overload. Which task or situation is taking the most energy?",
        "lonely_or_isolated": "That points to a connection gap. Is it about fewer people, or feeling unseen?",
        "question": "Good question. I would start by naming the specific situation and one possible next step.",
        "neutral": "Noted. A concrete example could make that easier to understand.",
    },
    "Casual Peer Agent": {
        "positive": "Honestly, that's nice to hear. Tiny wins still count.",
        "negative": "Yeah, that sounds rough. Hope today gives you at least one easier moment.",
        "tired_or_stressed": "Oof, that drained feeling is real. Maybe lower the bar a bit today.",
        "lonely_or_isolated": "That sounds really lonely. Social stuff can feel weirdly empty sometimes.",
        "question": "Good question. I don't have a perfect answer, but I'd start small.",
        "neutral": "Yeah, I get what you mean.",
    },
    "Reflective Agent": {
        "positive": "That feels worth holding onto, even if it is small.",
        "negative": "There is a lot of weight in that. Naming it can be its own kind of pause.",
        "tired_or_stressed": "Sometimes exhaustion says more about the load than the person carrying it.",
        "lonely_or_isolated": "Loneliness can be quiet and still take up a lot of space.",
        "question": "Maybe the question matters because it points to what you need next.",
        "neutral": "That makes sense as a moment to notice rather than rush past.",
    },
    "Neutral Peer Agent": {
        "positive": "That sounds pretty good. Worth keeping in mind.",
        "negative": "That does not sound easy. Hope it settles a bit.",
        "tired_or_stressed": "Sounds like a lot on your plate. One thing at a time might help.",
        "lonely_or_isolated": "That can feel heavy. Maybe one low-pressure check-in could help.",
        "question": "I would probably try the simplest option first and see what changes.",
        "neutral": "Fair point. I can see that.",
    },
}

TEMPLATES_ZH_CN = {
    "Supportive Agent": {
        "positive": "听起来这是个真实的亮点。你能注意到它，也很珍贵。",
        "negative": "听起来真的不容易。今天也请尽量对自己温柔一点。",
        "tired_or_stressed": "这样的疲惫很消耗人。哪怕只是稍微停一停，也算在照顾自己。",
        "lonely_or_isolated": "即使身边有人，孤独感也会很难受。谢谢你愿意在这里说出来。",
        "question": "这是个很值得想的问题。也许可以先从最容易尝试的一小步开始。",
        "neutral": "我听见了。谢谢你把这些感受说出来。",
    },
    "Analytical Agent": {
        "positive": "这是一个关于什么有效的有用信息。那个时刻与平时有什么不同？",
        "negative": "这听起来像一个很难受的模式。也许可以先把事实和自己的推测分开看。",
        "tired_or_stressed": "听起来像是负荷过高。哪项任务或情境最消耗你的精力？",
        "lonely_or_isolated": "这似乎指向一种连接上的缺口。是身边的人太少，还是觉得没人真正看见你？",
        "question": "这个问题很好。可以先明确具体情境，再列出一个可能的下一步。",
        "neutral": "了解。补充一个具体例子，可能会更容易看清它。",
    },
    "Casual Peer Agent": {
        "positive": "说真的，这听起来挺不错的。小小的顺利也算数。",
        "negative": "嗯，这确实挺难熬的。希望今天至少能有一小段轻松点的时间。",
        "tired_or_stressed": "唉，这种被耗空的感觉太真实了。今天可以稍微把标准放低一点。",
        "lonely_or_isolated": "这听起来真的很孤单。有时候社交明明不少，心里还是会空空的。",
        "question": "好问题。我也没有完美答案，不过可以先从小一点的尝试开始。",
        "neutral": "嗯，我明白你的意思。",
    },
    "Reflective Agent": {
        "positive": "这个瞬间值得被留住，哪怕它很小。",
        "negative": "这些话里有不少重量。把它说出来，本身也像是一小段停顿。",
        "tired_or_stressed": "有时候，疲惫更能说明肩上的负担，而不是说明你这个人。",
        "lonely_or_isolated": "孤独可能很安静，却依然会占据心里很大的空间。",
        "question": "也许这个问题之所以重要，是因为它正在指向你接下来真正需要的东西。",
        "neutral": "这个时刻值得先被看见，不必急着把它略过去。",
    },
    "Neutral Peer Agent": {
        "positive": "听起来还不错，可以记住这个感觉。",
        "negative": "这确实不太容易。希望它能慢慢缓下来。",
        "tired_or_stressed": "感觉你手头的事情很多。一次处理一件，可能会轻松些。",
        "lonely_or_isolated": "这会让人觉得很沉。或许可以先找一个人做一次没有压力的简单联系。",
        "question": "我大概会先试最简单的办法，再看看有什么变化。",
        "neutral": "有道理，我能理解。",
    },
}

ANSWER_TO_QUESTION_TEMPLATES = {
    "Supportive Agent": (
        '"{idea}" is a useful idea for the question I asked. I might give it some '
        "real space this afternoon and notice whether the pace feels different."
    ),
    "Analytical Agent": (
        '"{idea}" gives me something concrete to test. The interesting part will be '
        "whether it changes my energy or just how the time feels."
    ),
    "Casual Peer Agent": (
        '"{idea}" might be the move, honestly. That sounds much better than staring '
        "at the clock and waiting for the afternoon to fix itself."
    ),
    "Reflective Agent": (
        '"{idea}" changes the shape of the afternoon a little. Maybe a slow stretch '
        "of time needs a different rhythm rather than a way to escape it."
    ),
    "Neutral Peer Agent": (
        '"{idea}" sounds practical enough to actually try. I may put it on today\'s '
        "very short list."
    ),
}

ANSWER_TO_QUESTION_TEMPLATES_ZH_CN = {
    "Supportive Agent": (
        "“{idea}”确实回应了我刚才的问题。我想给它留一点时间试试，"
        "看看下午的节奏会不会因此变一变。"
    ),
    "Analytical Agent": (
        "“{idea}”给了我一个可以实际测试的办法。我会留意它改变的是精力，"
        "还是只是改变了我对时间的感觉。"
    ),
    "Casual Peer Agent": (
        "“{idea}”可能真是正解。总比盯着时钟，等下午自己恢复正常靠谱多了。"
    ),
    "Reflective Agent": (
        "“{idea}”好像能让下午换一种形状。也许缓慢的时间需要的是另一种节奏，"
        "不一定非得赶快摆脱它。"
    ),
    "Neutral Peer Agent": (
        "“{idea}”听起来够简单，也确实能试。我准备把它放进今天那张很短的待办里。"
    ),
}


def classify_comment(text: str, language: str = "en") -> str:
    safety = check_user_comment_safety(text, language)
    if safety.safety_flag:
        return "safety_sensitive"

    lowered = text.lower()
    words = set(re.findall(r"\b[a-zA-Z']+\b", lowered))
    if "?" in text or "？" in text:
        return "question"
    if words & LONELY_TERMS or _contains_any(text, CHINESE_LONELY_TERMS):
        return "lonely_or_isolated"
    if words & TIRED_TERMS or _contains_any(text, CHINESE_TIRED_TERMS):
        return "tired_or_stressed"
    if words & NEGATIVE_TERMS or _contains_any(text, CHINESE_NEGATIVE_TERMS):
        return "negative"
    if words & POSITIVE_TERMS or _contains_any(text, CHINESE_POSITIVE_TERMS):
        return "positive"
    return "neutral"


def _contains_any(text: str, terms: set[str]) -> bool:
    return any(term in text for term in terms)


class RuleBasedAgent:
    async def generate_reply(self, request: AgentRequest) -> AgentResult:
        start = time.perf_counter()
        safety = check_user_comment_safety(request.user_comment, request.language)
        persona = get_persona(request.agent_id)
        role = persona.role if persona else "Neutral Peer Agent"
        category = (
            "safety_sensitive"
            if safety.safety_flag
            else classify_comment(request.user_comment, request.language)
        )

        if safety.safety_flag and safety.reply_text:
            reply = safety.reply_text
        elif request.world_role_context is not None:
            from agents.role_prompt import role_fallback
            reply = role_fallback(request)
        elif _is_answer_to_agent_question(request):
            answer_templates = (
                ANSWER_TO_QUESTION_TEMPLATES_ZH_CN
                if request.language == "zh-CN"
                else ANSWER_TO_QUESTION_TEMPLATES
            )
            reply = answer_templates.get(
                role,
                answer_templates["Neutral Peer Agent"],
            ).format(idea=_short_idea(request.user_comment))
        else:
            templates = TEMPLATES_ZH_CN if request.language == "zh-CN" else TEMPLATES
            reply = templates.get(role, templates["Neutral Peer Agent"]).get(
                category,
                templates["Neutral Peer Agent"]["neutral"],
            )
            if (
                request.agent_memory.get("comment_count", 0)
                and request.agent_memory.get("last_post_id") != request.post_id
            ):
                memory_prefix = (
                    "我记得我们之前也聊过。"
                    if request.language == "zh-CN"
                    else "I remember we talked before. "
                )
                reply = f"{memory_prefix}{reply}"

        latency_ms = int((time.perf_counter() - start) * 1000)
        prompt_version = persona.prompt_version if persona else "rule-v1"
        if request.world_role_context is not None:
            prompt_version = "world-role-prompt-v2"
        return AgentResult(
            reply_content=reply,
            generation_mode="rule",
            model_provider=None,
            model_name=None,
            prompt_version=prompt_version,
            safety_flag=safety.safety_flag,
            latency_ms=latency_ms,
            metadata={
                "category": category,
                "language": request.language,
                "memory_used": bool(request.agent_memory.get("comment_count", 0)),
                "interaction_kind": request.interaction_kind,
            },
        )


def _is_answer_to_agent_question(request: AgentRequest) -> bool:
    relation = request.reply_relation.lower()
    return (
        "回答帖子作者" in request.reply_relation
        or "answering the post author's question" in relation
        or "offering an idea the author requested" in relation
    )


def _short_idea(content: str) -> str:
    cleaned = content.strip().strip("\"'“”‘’").rstrip("。.!！?？")
    return cleaned[:60] or "这个办法"
