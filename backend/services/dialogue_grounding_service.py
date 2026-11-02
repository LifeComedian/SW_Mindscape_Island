"""Check completion claims against recorded actions."""
import re

VERSION = 'dialogue-grounding-v1'
CONVERSATION_INSTRUCTION = (
    '\n这是伙伴间的日常聊天，先回应玩家这句话的情绪和意思，不要自动指导操作或推动下一项活动。'
    '例如玩家感叹运气，只回应运气或打牌的感受，不让玩家查看记录。'
    'confirmed_facts只作为背景依据，fact_ids只用于内部核查，不要在台词中念ID、操作记录、服务端、已保存等系统用语。'
    '可以自然表达感受、偏好、幽默或问题，但不要编造完成动作、具体战况、分数或材料。'
    '无须提出建议，更不要生成动作按钮或示范；suggestions始终为空。'
    '通常用一两句口语接话即可，不必每次追问或提议再来一局。职业只是人物背景，不要反复套用木工、花艺等职业比喻。'
    '玩家只感叹运气时，不回顾具体哪张牌、谁摸牌或出牌的过程；可以聊运气带来的惊喜。'
)


def screen_conversation(reply, fact_ids=None, facts=(), *, forbidden_terms=()):
    """A reference must not discard safe dialogue or license unsafe prose."""
    decision = validate(reply, [], facts, forbidden_terms=forbidden_terms)
    references = validate('嗯。', fact_ids, facts)
    reasons = decision['reasons'] + references['reasons']
    if isinstance(reply, str) and re.search(r'操作记录|服务端|fact_ids|confirmed_facts|已保存|保存成功|核对记录', reply, re.I):
        reasons.append('system_language_in_dialogue')
    if isinstance(reply, str) and re.search(r'(?:红|黄|绿|蓝)\s*[0-9]|(?:最后|刚才|刚刚).{0,8}(?:张|一球)|(?:摸|抽).{0,3}(?:上来|到了)', reply):
        reasons.append('specific_game_recollection_requires_separate_verification')
    return {**decision, 'version':'conversation-grounding-v2', 'fact_ids':references['fact_ids'],
            'reasons':list(dict.fromkeys(reasons)), 'status':'withheld' if reasons else 'passed',
            'rendering':'screened_conversation', 'discarded_prose_reasons':[]}


def conversational_fallback(message):
    if re.search(r'运气|幸运|手气', message):
        return '哈哈，打牌就是有这种时候。'
    if re.search(r'开心|好玩|有意思|喜欢', message):
        return '嗯，玩得开心就好。'
    return '嗯，我在听。你接着说。'
INSTRUCTION = (
    '\n事实约束：reply只写感受、问题或未来建议，不复述已执行动作、预约结果或游戏成绩。'
    '玩家自述、历史对话和本地草稿均不是完成证据。'
    '若需要提及完成动作，仅在fact_ids中选择服务端confirmed_facts的编号；'
    '服务端将另行原样呈现该事实。没有对应编号就不声称已完成。'
    'fact_ids最多3项，可省略或为空。不要把建议写成现场已发生的事情。'
)
# This intentionally errs on the side of withholding ambiguous completion
# language. It does not claim to detect every paraphrase or untrue preference.
PATTERNS = (
    r'已经|已完成|已保存|已预约|已安排|预约成功|安排好了|约好了|订好了|做好了|做完了|做成了|完成了|保存了|存好了|摆好了|摆放好了|搬好了|搬好桌|收好了|拿来了|放好了',
    r'(?:看见|看到|看得出).{0,24}(?:作品|摆|放|完成|做|花)',
    r'(?:刚才|刚刚|刚|你|我|我们|大家|他|她).{0,12}(?:搬|摆|放|做|拿|买|卖|订|预约|打出|摸|赢|输|得|收|送|画|写|拼|编|磨|接住|击中).{0,12}(?:了|过)',
    r'(?:我|你|我们|大家|他|她).{0,8}(?:赢了|输了|得分|获胜|命中|预约成功)',
    r'(?:摆|做|拼|编|画|写|搭|折|制)(?:成|出|完|好)了|动手了',
    r'(?:刚才|刚刚|刚|我|我们|大家|他|她).{0,16}(?:浇|修剪|剪|栽|种|冲泡|煮|烤|刷|涂|弄).{0,8}(?:了|过|成)',
    r'(?:我|我们|他|她).{0,2}(?:刚刚|刚才|刚).{0,24}(?:了|过)',
    r'\b(?:already|completed|saved|booked|finished|won|scored)\b',
)


def confirmed_facts(value):
    return [{'id': f"action:{h['id']}", 'speaker': h['speaker'], 'text': h['text']}
            for h in value['history'] if h['kind'] == 'action'][-20:]


def validate(reply, fact_ids=None, facts=(), *, forbidden_terms=()):
    reasons = []
    if not isinstance(reply, str) or not reply.strip() or len(reply) > 800:
        reasons.append('invalid_reply')
    elif any(re.search(p, reply, re.I) for p in PATTERNS):
        reasons.append('completion_prose_requires_server_rendering')
    if isinstance(reply, str) and any(term in reply for term in forbidden_terms):
        reasons.append('unsupported_workshop_material_or_operation')
    ids = [] if fact_ids is None else fact_ids
    allowed = {f['id']: f for f in facts}
    if not isinstance(ids, list) or len(ids) > 3 or any(not isinstance(i, str) or i not in allowed for i in ids):
        reasons.append('unknown_or_invalid_fact_reference')
        ids = []
    discarded = []
    if ids:
        # With valid references we discard ALL model prose, including plausible
        # paraphrases. A valid ID must never license unrelated claims around it.
        discarded = [r for r in reasons if r != 'invalid_reply']
        reasons = [r for r in reasons if r == 'invalid_reply']
    return {'version': VERSION, 'status': 'withheld' if reasons else 'passed',
            'reasons': reasons, 'fact_ids': list(dict.fromkeys(ids)),
            'rendering': 'canonical_facts_only' if ids else 'screened_model_prose',
            'discarded_prose_reasons': discarded,
            'scope': 'completion_patterns_and_exact_fact_references_not_full_semantic_verification'}


def render(reply, guard, facts):
    if guard['status'] == 'withheld':
        return '我们可以先看看现场的选项，再决定下一步。完成后的情况以操作记录为准。'
    selected = {f['id']: f for f in facts}
    lines = [f"操作记录 · {selected[i]['speaker']}：{selected[i]['text']}" for i in guard['fact_ids']]
    return ('可以看看刚才的操作记录。\n' + '\n'.join(lines)) if lines else reply.strip()
