"""Topic continuity and turn-level dialogue checks."""
import json
import re
from difflib import SequenceMatcher

PLAYER = {'player', 'participant', 'user', '你'}
QUESTION = re.compile(r'[？?]|(?:吗|么)[。！!]*$')
CLOSE = re.compile(r'再见|拜拜|明天见|下次见|先不聊|不聊了|各自坐|先去.{0,8}(?:转转|逛|忙)|今天先这样')
REQUEST = re.compile(r'怎么办|怎么做|怎么画|怎么开始|从哪.{0,5}开始|该从.{0,5}开始|能.{0,6}试|给.{0,4}建议|有什么建议|教我|有什么办法|该如何|技巧')
COACHED_ADVICE = re.compile(r'(?:要是|如果|不如|不妨|你可以|要不要|试着|先试试).{0,25}(?:提一提|说出来|试一试|练习|动笔|放下|改变|列个|每天|写下来)|先.{0,12}(?:提一提|试一试|练习).{0,16}(?:会不会|是不是|轻松|好一点)|'
    r'(?:有时候|有时|能|可以|不妨)先.{0,16}(?:弄出|做出|看见|试|练|动笔|说出来)|'
    r'(?:难的时候|累的时候|不高兴了|觉得难了).{0,8}(?:就|先).{0,6}(?:放下|停下来|换个)|'
    r'你(?:可以|不妨|不如|应该).{0,12}(?:每天|练习|试着|写下来|列个|放下)')


def question_parts(text):
    return [s for s in re.findall(r'[^。！？!?；;\n]+[。！？!?；;\n]*', text) if QUESTION.search(s)]


def turn_policy(message, history):
    npc = [str(h.get('content', h.get('text', ''))) for h in history
           if h.get('speaker') not in PLAYER | {'现场', 'system'}][-4:]
    previous = question_parts(npc[-1]) if npc else []
    return {'advice_requested': bool(REQUEST.search(message)),
            'closing': bool(CLOSE.search(message)),
            'question_budget': 0 if previous or CLOSE.search(message) else 1,
            'recent_questions': [q for t in npc for q in question_parts(t)],
            'instruction': ('玩家明确求办法，本轮给一个贴合他刚说的处境、可以自行选择的小尝试，并说明为什么；不能用“不急着找办法”回避回答。' if REQUEST.search(message) else '')+'上一轮已经问过时，这轮先回应答案，用看法或理解推进，不换种说法再问；零问题也能深入。必要交易/邀约信息不靠猜测，缺信息可直说。'}


def local_blocks(text, message, history, facts):
    from agents.dialogue_quality import sentences
    policy = turn_policy(message, history)
    maps = []
    for fact in facts:
        if not str(fact.get('id', fact.get('fact_ref', ''))).startswith('map:'):
            continue
        value = fact
        if isinstance(fact.get('text'), str):
            try: value = json.loads(fact['text'])
            except (ValueError, TypeError): continue
        if isinstance(value, dict) and isinstance(value.get('data'), dict):
            maps.append(value['data'].get('places', []))
    map_text = json.dumps(maps, ensure_ascii=False) if maps else ''
    result = []
    for i, sentence in enumerate(sentences(text)):
        question = bool(question_parts(sentence))
        if question and (policy['question_budget'] == 0 or any(
                SequenceMatcher(None, sentence.strip(), q.strip()).ratio() >= .72
                for q in policy['recent_questions'])):
            result.append({'index': i, 'kind': 'repeated_question', 'reason': '上一轮已提问或与近期问题近似，本轮应回应玩家的回答。', 'source': 'turn_rule'})
        if not policy['advice_requested'] and COACHED_ADVICE.search(sentence):
            result.append({'index': i, 'kind': 'unsolicited_instruction', 'reason': '未请求办法却用试做建议推动改变，包括包装成问题的建议。', 'source': 'turn_rule'})
        # Validate suggested places against the world map.
        if map_text and re.search(r'去|到|在|那边|那里|坐|看夕阳', sentence) and not re.search(r'不(?:知道|确定|清楚)|没(?:听说|见过)|并没有|不存在|没有.{0,6}(?:露台|天台)', sentence):
            for noun in ('露台', '天台', '屋顶花园', '灯塔', '观景塔', '山顶', '码头', '排球室', '海堤', '屋顶'):
                if noun in sentence and noun not in map_text:
                    result.append({'index': i, 'kind': 'unsupported_fact', 'reason': '可到达地点目录未提供“'+noun+'”，不能把它作为游戏目的地。', 'source': 'map_rule'})
    return result
