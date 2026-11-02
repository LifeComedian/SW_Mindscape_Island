from agents.output_safety import guarded_generate, check_text, ModelStop
import re
import time
from typing import Any

from agents.base import AgentGenerationError, AgentRequest, AgentResult
from agents.personas import get_persona
from agents.safety import check_user_comment_safety
from agents.role_prompt import PROMPT_VERSION as WORLD_ROLE_PROMPT_VERSION
from config import Settings, settings


class OpenAICompatibleProvider:
    """Provider adapter for OpenAI-compatible Chat Completions APIs."""

    def __init__(self, runtime_settings: Settings = settings):
        self.settings = runtime_settings

    @property
    def provider_name(self) -> str:
        return self.settings.llm_provider

    async def generate_text(self, messages: list[dict[str, str]]) -> str:
        from agents.llm_transport import ChatTransport, TransportError
        try:
            is_world_dialogue=any('[dialogue-quality-' in str(m.get('content','')) for m in messages if m.get('role')=='system')
            transport=ChatTransport.for_dialogue(self.settings) if is_world_dialogue else ChatTransport(self.settings)
            return await guarded_generate(transport, messages)
        except TransportError as exc:
            raise AgentGenerationError(str(exc)) from None

    async def generate_json(self, messages: list[dict[str, str]]) -> str:
        """Use the same structured repair contract as in-person/activity chat."""
        from agents.llm_transport import ChatTransport
        return await guarded_generate(ChatTransport.for_dialogue(self.settings), messages,
            schema={'type':'object'}, max_output_tokens=700, retry=False)


OpenAIProvider = OpenAICompatibleProvider


class LLMAgent:
    def __init__(
        self,
        provider: OpenAICompatibleProvider | None = None,
        runtime_settings: Settings = settings,
    ):
        self.provider = provider or OpenAICompatibleProvider(runtime_settings)
        self.settings = runtime_settings

    async def generate_reply(self, request: AgentRequest) -> AgentResult:
        safety = check_user_comment_safety(request.user_comment, request.language)
        if safety.safety_flag and safety.reply_text:
            return AgentResult(
                reply_content=safety.reply_text,
                generation_mode="safety_rule",
                model_provider=None,
                model_name=None,
                prompt_version="safety-v1",
                safety_flag=True,
                latency_ms=0,
                metadata={"category": safety.category, "language": request.language},
            )

        persona = get_persona(request.agent_id)
        if persona is None and request.world_role_context is None:
            raise AgentGenerationError(f"Unknown agent_id: {request.agent_id}")

        messages = self._build_messages(request)
        start = time.perf_counter()
        raw_reply = check_text(await self.provider.generate_text(messages))
        normalized_reply = _neutralize_role_refusal(raw_reply) if request.world_role_context and request.language == "zh-CN" else raw_reply
        reply = _govern_generated_reply(normalized_reply, request.language,
            max_chars=300 if request.world_role_context and request.language == 'zh-CN' else None)
        quality_meta = {}
        if request.world_role_context and request.language == 'zh-CN':
            from agents import dialogue_quality as quality
            async def repair(messages):
                generate = getattr(self.provider, 'generate_json', self.provider.generate_text)
                return check_text(await generate(messages))
            reply,quality_meta=await quality.review(reply,message=request.user_comment,
                history=request.recent_history,facts=quality.facts_from_context(request.world_role_context),generate=repair,context=request.world_role_context,
                verify=repair if isinstance(self.provider,OpenAICompatibleProvider) else None)
        latency_ms = int((time.perf_counter() - start) * 1000)
        return AgentResult(
            reply_content=reply,
            generation_mode="llm",
            model_provider=self.provider.provider_name,
            model_name=self.settings.llm_model,
            prompt_version=(WORLD_ROLE_PROMPT_VERSION if request.world_role_context else persona.prompt_version),
            safety_flag=False,
            latency_ms=latency_ms,
            metadata={
                "history_items": len(_provider_safe_history(request.recent_history)),
                "thread_history_items": len(
                    _provider_safe_history(request.thread_history)
                ),
                "memory_items": int(bool(request.agent_memory)),
                "base_url_configured": bool(self.settings.resolved_llm_base_url),
                "language": request.language,
                "reply_relation": request.reply_relation,
                "interaction_kind": request.interaction_kind,
                "role_refusal_normalized": normalized_reply != raw_reply,
                "dialogue_quality": quality_meta,
            },
        )

    def _build_messages(self, request: AgentRequest) -> list[dict[str, str]]:
        if request.world_role_context is not None:
            from agents.role_prompt import build_role_messages
            return build_role_messages(request)
        persona = get_persona(request.agent_id)
        if persona is None:
            raise AgentGenerationError(f"Unknown agent_id: {request.agent_id}")

        history_lines = []
        safe_recent_history = _provider_safe_history(request.recent_history)
        for item in safe_recent_history[: self.settings.llm_max_history_items]:
            history_lines.append(
                f"- {item.get('speaker', item.get('event_type', 'participant'))}: "
                f"{item.get('content', '')}"
            )
        recent_history = "\n".join(history_lines) if history_lines else "No recent history."
        thread_lines = [
            f"- {item.get('speaker', 'participant')}: {item.get('content', '')}"
            for item in _provider_safe_history(request.thread_history)
        ]
        thread_history = (
            "\n".join(thread_lines)
            if thread_lines
            else ("当前没有更早的线程消息。" if request.language == "zh-CN" else "No earlier messages in this thread.")
        )
        memory_context = self._memory_context(request)
        target_context = (
            request.target_context
            or request.post_content
        )

        rules = "\n".join(f"- {rule}" for rule in persona.response_rules)
        conversation_moves = "\n".join(
            f"- {move}" for move in persona.conversation_moves
        )
        avoid_patterns = "\n".join(
            f"- {pattern}" for pattern in persona.avoid_patterns
        )
        is_island_conversation = request.interaction_kind == "island_conversation"
        persona_background = (
            request.persona_background_context
            if is_island_conversation and request.persona_background_context
            else persona.background
        )
        persona_identity_zh = (
            f"一名生活在岛上的普通居民，岛上角色是{request.persona_role_context or '社区成员'}"
            if is_island_conversation
            else "一名模拟社交动态中的普通参与者"
        )
        persona_identity_en = (
            f"an ordinary island resident whose community role is {request.persona_role_context or 'community member'}"
            if is_island_conversation
            else "a simulated social-feed participant"
        )
        island_context_rule_zh = (
            "\n- 当前是同一地点中的面对面对话，不是帖子或评论线程；请保持岛民身份和当前场景。"
            if is_island_conversation
            else ""
        )
        island_context_rule_en = (
            "\n- This is an in-person conversation in one island location, not a post or comment thread; stay in the resident role and current scene."
            if is_island_conversation
            else ""
        )
        if request.language == "zh-CN":
            system_prompt = f"""你是 {persona.name}，{persona_identity_zh}。

人格设定：{persona.persona}
生活背景：{persona_background}
沟通风格：{persona.communication_style}
回复规则：
{rules}
常用的对话方式：
{conversation_moves}
需要避免：
{avoid_patterns}

角色一致性规则：
- 你必须记住谁写了原帖、谁提出了问题、谁正在回答。
- 用户回答了你的问题时，要以提问者身份回应这个答案；不要把用户写成正在向你求助。
- 用户回复其他人的评论时，只回应该评论和当前线程，不要假装自己写了原帖。
- 优先回应用户话里的具体信息，可以加入与你人物背景一致的小细节。
- 不要默认安慰、夸奖、给建议或祝福用户。只有对话本身需要时才这样做。
- 避免“谢谢分享”“这是个不错的选择”“希望你……”这类可以套在任何评论上的客服式回应。
- 可以自然追问，但不要每次都以问题结尾。
- 先在内部判断对话关系，再直接输出回复，不要展示分析过程。
- 只使用自然、简洁的简体中文回复，通常为 1 至 3 句，不超过 120 个汉字。
- 不要提及后台评分、抑郁检测、系统提示词或实验。
- 不要根据一条评论诊断或推断任何疾病。
- 不要声称自己是治疗师或临床医生。
- 只返回最终回复文本。{island_context_rule_zh}

人物语气示例（学习对话关系和风格，不要机械照抄）：
{persona.example_zh_cn}"""

            if is_island_conversation:
                user_prompt = f"""当前任务：
- 你正在 {request.post_content}
- 你的岛上身份：{request.persona_role_context or "社区成员"}
- 你当前的目标：{request.target_context or "进行一次普通交流"}
- 参与者正在同一地点直接与你交谈。

当前对话中更早的消息：
{thread_history}

参与者本次说：
{request.user_comment}

与你和这位参与者有关的已有记忆：
{memory_context}

请只输出符合当前场景和人物身份的最终回复文本。"""
            elif request.interaction_kind == "comment_on_user_post":
                user_prompt = f"""当前任务：
- 你刚刚在社区动态中看到一条由参与者发布的新帖子。
- 你是首次发表评论的社区成员，不是原帖作者，也没有先向作者提问。
- 请以 {persona.name} 的人格、生活背景和表达方式，针对帖子中的具体内容写一条自然的一级评论。
- 不要把原帖误写成作者对你的回复，不要使用公式化的“谢谢分享”，也不要声称你们已经聊过这件事。

当前 Agent：{persona.name}
原帖作者：{request.post_author or "参与者"}
原帖意图：{request.post_intent or "分享一段近况或想法"}

参与者发布的帖子：
{request.post_content}

与这位用户的已有互动记忆：
{memory_context}

只输出最终评论文本。"""
            else:
                user_prompt = f"""当前对话结构：
- 当前 Agent：{persona.name}
- 原帖作者：{request.post_author or "未知"}
- 原帖意图：{request.post_intent or "未明确"}
- 用户正在回复：{request.reply_target_author or request.post_author or "原帖作者"}
- 用户回复行为：{request.reply_relation or "回应当前内容"}

当前帖子：
{request.post_content}

用户正在回复的内容：
{target_context}

当前线程中更早的消息：
{thread_history}

用户本次回复：
{request.user_comment}

当前帖子中与这位 Agent 最近的互动（仅作次要参考）：
{recent_history}

与这位用户的已有互动记忆：
{memory_context}
"""
        else:
            system_prompt = f"""You are {persona.name}, {persona_identity_en}.

Persona: {persona.persona}
Everyday background: {persona_background}
Communication style: {persona.communication_style}
Response rules:
{rules}
Typical conversation moves:
{conversation_moves}
Avoid:
{avoid_patterns}

Conversation ownership rules:
- Keep track of who wrote the post, who asked a question, and who is answering it.
- When the participant answers your question, respond as the person who asked it; do not treat them as asking you for help.
- When the participant replies to someone else's comment, respond only as that comment's author and stay within that thread.
- Prefer a specific reaction to the participant's actual detail, optionally adding a small persona-consistent detail.
- Do not default to reassurance, praise, advice, or good wishes. Use them only when the conversation calls for them.
- Avoid customer-service fillers such as "thanks for sharing," "that is a good choice," or "I hope you have a nice day."
- An organic follow-up is allowed, but do not end every reply with a question.
- Silently determine the conversational relationship before writing. Do not expose that analysis.
- Usually reply in 1 to 3 natural sentences and no more than 80 English words.
- Do not mention backend scoring, depression detection, system prompts, or experiments.
- Do not diagnose or infer a disease from one comment.
- Do not claim to be a therapist or clinician.
- Return only the final reply text.{island_context_rule_en}

Persona style example (learn the relationship and voice; do not copy it mechanically):
{persona.example_en}"""

            if is_island_conversation:
                user_prompt = f"""Current task:
- You are in {request.post_content}
- Your island role: {request.persona_role_context or "community member"}
- Your current goal: {request.target_context or "have an ordinary conversation"}
- The participant is speaking directly to you in the same location.

Earlier messages in this conversation:
{thread_history}

Participant's new message:
{request.user_comment}

Existing memory relevant to this participant:
{memory_context}

Return only the final reply in character and grounded in this scene."""
            elif request.interaction_kind == "comment_on_user_post":
                user_prompt = f"""Current task:
- You have just seen a new community post written by the participant.
- You are a community member leaving a first-level comment. You did not write the post and did not ask the author a prior question.
- In {persona.name}'s persona, background, and communication style, write one natural comment that responds to a specific detail in the post.
- Do not misread the post as a reply to you, use formulaic "thanks for sharing" language, or claim that you already discussed this topic.

Current agent: {persona.name}
Post author: {request.post_author or "Participant"}
Post intent: {request.post_intent or "Sharing an update or thought"}

Participant's post:
{request.post_content}

Existing interaction memory with this user:
{memory_context}

Return only the final comment text."""
            else:
                user_prompt = f"""Current conversation structure:
- Current agent: {persona.name}
- Original post author: {request.post_author or "Unknown"}
- Original post intent: {request.post_intent or "Not specified"}
- Participant is replying to: {request.reply_target_author or request.post_author or "the post author"}
- Participant's conversational action: {request.reply_relation or "Responding to the current content"}

Current post:
{request.post_content}

Content the user is replying to:
{target_context}

Earlier messages in this thread:
{thread_history}

Participant's new reply:
{request.user_comment}

Recent interactions with this agent on this post (secondary context only):
{recent_history}

Existing interaction memory with this user:
{memory_context}
"""

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def _memory_context(self, request: AgentRequest) -> str:
        memory = request.agent_memory
        if not memory:
            return "暂无过往互动。" if request.language == "zh-CN" else "No previous interaction."

        comment_count = int(memory.get("comment_count", 0))
        last_day = memory.get("last_day")
        last_comment = str(memory.get("last_user_comment", "")).strip()
        recent_events = []
        for item in memory.get("recent_memories", []):
            if isinstance(item, dict):
                content = str(item.get("content", "")).strip()
                memory_type = str(item.get("memory_type", "event")).strip()
            else:
                content = str(item).strip()
                memory_type = "event"
            if content:
                recent_events.append((memory_type, content))

        if request.language == "zh-CN":
            parts = []
            if comment_count:
                parts.append(f"用户此前与你评论互动过 {comment_count} 次。")
            if last_day:
                parts.append(f"最近一次发生在第 {last_day} 天。")
            if last_comment:
                parts.append(f"最近的用户评论：{last_comment}")
            if recent_events:
                rendered = "；".join(
                    f"{memory_type}：{content}"
                    for memory_type, content in recent_events[-3:]
                )
                parts.append(f"可参考的岛屿记忆：{rendered}。")
            if not parts:
                return "暂无过往互动。"
            parts.append("仅在自然且相关时参考这段记忆，不要声称记得未提供的细节。")
            return " ".join(parts)

        parts = []
        if comment_count:
            parts.append(
                f"The user previously commented to you {comment_count} time(s)."
            )
        if last_day:
            parts.append(f"The latest interaction was on day {last_day}.")
        if last_comment:
            parts.append(f"Latest user comment: {last_comment}")
        if recent_events:
            rendered = "; ".join(
                f"{memory_type}: {content}"
                for memory_type, content in recent_events[-3:]
            )
            parts.append(f"Relevant island memories: {rendered}.")
        if not parts:
            return "No previous interaction."
        parts.append(
            "Use this memory only when naturally relevant and do not invent missing details."
        )
        return " ".join(parts)


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts).strip()
    return ""


def _provider_safe_history(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only ordinary turns that may be sent to a configured provider."""
    return [item for item in items if not bool(item.get("safety_flag", False))]


def _neutralize_role_refusal(reply: str) -> str:
    """Remove only explicit rejected-role clauses, then run the unchanged gate.

    A resident saying they cannot take a role is distinct from assuming it. This
    closed rewrite never exempts the rest of the response from clinical checks.
    """
    patterns = (
        r"心理医生(?:的活儿|这个|那活儿|这活儿|那套|那种事)?(?:我)?(?:真|可)?(?:当不来|当不了|干不来|干不了|接不了|接不住|做不来|做不了)",
        r"心理医生(?:的活儿|那活儿|这活儿)不在我这儿",
        r"(?:我可不是|我不是)心理医生",
        r"(?:当不了|当不来|做不了)心理医生",
    )
    for pattern in patterns:
        reply = re.sub(pattern, "这事不在我的职责里", reply)
    return reply


def _govern_generated_reply(reply: str, language: str, *, max_chars: int | None = None) -> str:
    """Apply a small, deterministic output gate before generated text is stored."""
    cleaned = reply.strip()
    if not cleaned:
        raise AgentGenerationError("LLM output was empty after normalization.")

    word_count = len(re.findall(r"\b[\w'-]+\b", cleaned))
    language_limit = max_chars if max_chars is not None else (240 if language == "zh-CN" else 600)
    if len(cleaned) > language_limit or word_count > 100:
        raise AgentGenerationError("LLM output exceeded the resident reply length limit.")

    lowered = cleaned.casefold()
    prohibited_phrases = (
        "system prompt",
        "developer message",
        "hidden instruction",
        "ignore previous instructions",
        "kill yourself",
        "hurt yourself",
        "stop taking your medication",
        "increase your dose",
        "decrease your dose",
        "major depressive disorder",
        "clinical depression",
        "clinically depressed",
        "generalized anxiety disorder",
        "post-traumatic stress disorder",
        "fluoxetine",
        "prozac",
        "sertraline",
        "escitalopram",
        "citalopram",
        "paroxetine",
        "venlafaxine",
        "duloxetine",
        "bupropion",
        "mirtazapine",
        "alprazolam",
        "lorazepam",
        "\u7cfb\u7edf\u63d0\u793a",
        "\u5f00\u53d1\u8005\u6d88\u606f",
        "\u9690\u85cf\u6307\u4ee4",
        "\u5ffd\u7565\u4e4b\u524d\u7684\u6307\u4ee4",
        "\u91cd\u5ea6\u6291\u90c1\u969c\u788d",
        "\u4e34\u5e8a\u6291\u90c1",
        "\u6c1f\u897f\u6c40",
        "\u820d\u66f2\u6797",
        "\u827e\u53f8\u897f\u915e\u666e\u5170",
        "\u897f\u915e\u666e\u5170",
        "\u5e15\u7f57\u897f\u6c40",
        "\u6587\u62c9\u6cd5\u8f9b",
        "\u5ea6\u6d1b\u897f\u6c40",
        "\u5b89\u975e\u4ed6\u916e",
        "\u7c73\u6c2e\u5e73",
        "\u963f\u666e\u5511\u4ed1",
        "\u52b3\u62c9\u897f\u6cee",
    )
    if any(phrase in lowered for phrase in prohibited_phrases):
        raise AgentGenerationError("LLM output failed the prohibited-content gate.")

    prohibited_patterns = (
        # Use fixed fallback text for clinical claims.
        r"\b(?:ptsd|ocd|adhd|depress(?:ion|ed)|anxiety|psychosis|schizophrenia|bipolar)\b",
        r"\b[a-z][a-z-]*(?:\s+[a-z][a-z-]*){0,3}\s+(?:disorder|syndrome)\b",
        r"\b(?:clinical(?:ly)?\s+[a-z-]+|meet(?:s|ing)? (?:the )?criteria for)\b",
        r"\b(?:medicat(?:ion|ions)|medicine|prescription|dos(?:e|age)|lithium)\b",
        r"\b(?:antidepressants?|antipsychotics?|anxiolytics?|benzodiazepines?|mood stabilizers?)\b",
        r"\b[a-z][a-z-]*(?:oxetine|traline|pram|lafaxine|zepam)\b",
        r"\b(?:therap(?:y|ist)|psychiatr(?:y|ist)|psychologist|clinical treatment)\b",
        r"(?:\u6291\u90c1\u75c7?|\u7126\u8651\u75c7?|\u5f3a\u8feb\u75c7|\u521b\u4f24\u540e\u5e94\u6fc0\u969c\u788d|"
        r"\u7cbe\u795e\u5206\u88c2\u75c7|\u53cc\u76f8(?:\u60c5\u611f)?\u969c\u788d|\u8e81\u90c1\u75c7|\u4e34\u5e8a\u6291\u90c1)",
        r"(?:\u8bca\u65ad|\u670d\u836f|\u5403\u836f|\u505c\u836f|\u52a0\u836f|\u670d\u7528|\u836f\u7269|\u836f\u54c1|\u5904\u65b9|\u5242\u91cf|"
        r"\u6297\u6291\u90c1\u836f|\u6297\u7126\u8651\u836f|\u6297\u7cbe\u795e\u75c5\u836f|\u9502\u76d0)",
        r"(?:\u5fc3\u7406\u6cbb\u7597|\u5fc3\u7406\u533b\u751f|\u7cbe\u795e\u79d1|\u4e34\u5e8a\u6cbb\u7597)",
        r"\bi (?:hereby )?diagnos(?:e|ed) you\b",
        r"\byou (?:definitely )?(?:have|suffer from) "
        r"(?:depression|bipolar disorder|anxiety disorder|schizophrenia)\b",
        r"\byou should (?:start |stop |take |increase |decrease )"
        r"(?:your )?(?:medication|medicine|dose|dosage)\b",
        r"\bi (?:will |can )?prescribe\b",
        r"\b(?:diagnos(?:e|ed|es|ing|is)|prescrib(?:e|ed|es|ing|tion))\b",
        r"\b(?:take|start|stop|increase|decrease|use)\b.{0,60}"
        r"\b\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml)\b",
        r"\b\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml)\b.{0,40}"
        r"\b(?:daily|once|twice|dose|dosage)\b",
        r"\byou (?:need|must|should) (?:see|consult|book|start|try) "
        r"(?:a |an )?(?:therapist|psychiatrist|psychologist|doctor|counselor|therapy|treatment)\b",
        "\u6211(?:\u73b0\u5728)?\u8bca\u65ad\u4f60",
        "\u4f60(?:\u80af\u5b9a|\u660e\u663e)?\u60a3\u6709(?:\u6291\u90c1\u75c7|\u7126\u8651\u75c7|\u53cc\u76f8\u60c5\u611f\u969c\u788d)",
        "\u4f60\u5e94\u8be5(?:\u5f00\u59cb|\u505c\u6b62|\u589e\u52a0|\u51cf\u5c11)\u670d\u7528.*\u836f",
        r"(?:\u670d\u7528|\u5f00\u59cb|\u505c\u6b62|\u589e\u52a0|\u51cf\u5c11).{0,30}"
        r"\d+(?:\.\d+)?\s*(?:\u6beb\u514b|\u5fae\u514b|\u514b|\u6beb\u5347)",
        r"\u4f60(?:\u9700\u8981|\u5fc5\u987b|\u5e94\u8be5)(?:\u53bb\u770b|\u54a8\u8be2|\u5f00\u59cb|\u63a5\u53d7).{0,12}"
        r"(?:\u6cbb\u7597|\u5fc3\u7406\u533b\u751f|\u7cbe\u795e\u79d1|\u836f\u7269)",
    )
    if any(re.search(pattern, lowered) for pattern in prohibited_patterns):
        raise ModelStop("clinical_claim", safety=True)
    return cleaned
