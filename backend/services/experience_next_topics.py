"""Contextual topic suggestions with daily limits."""
import json,re
from pathlib import Path
from models import WorldConversationTurn, WorldAction
from content.experience_next import enabled

def topic_fact(db,world,agent_id):
    if not enabled():return []
    cards=json.loads((Path(__file__).resolve().parents[1]/'content/experience_next_topics.json').read_text(encoding='utf-8'))
    turns=db.query(WorldConversationTurn).filter_by(session_id=world.session_id).all()
    replies=[(t.world_day,t.speaker_id,t.content or '') for t in turns if t.speaker_type in ('agent','resident')]
    for row in db.query(WorldAction).filter_by(session_id=world.session_id,action_type='private_message').all():
        replies.append((row.world_day,row.target_agent_id,json.loads(row.metadata_json or '{}').get('result',{}).get('reply','')))
    used={c['id'] for c in cards if any(c['opening'] in text for _,_,text in replies)}
    # Limit suggestions to one per actor and two per day; sensitive topics are user-led.
    today=[(actor,text) for day,actor,text in replies if day==world.current_day]
    count=sum(any(c['opening'] in text for c in cards) for _,text in today)
    mine=any(actor==agent_id and any(c['opening'] in text for c in cards) for actor,text in today)
    candidates=[c for c in cards if c['id'] not in used and (c['sensitivity']=='player_led_only' or not (count>=2 or mine))]
    return [{'fact_ref':'topics:optional','type':'dialogue_policy','data':{'candidates':candidates,'rule':'只有玩家话语/真实共同经历满足触发条件时才可选一个；可以完全不用。必须原样使用开场以记录跨人物去重。不要提构念、卡片或测试。玩家主动深入时继续理解，无需另开题。'}}]

def select_relevant(facts,message):
    result=[]
    patterns={1:r'一起|一个人|聚会|自己逛',2:r'不同意|意见|想法',3:r'来劲|累|兴奋',4:r'朋友.*烦|关心',5:r'不愿意|界限|不舒服',6:r'信任|放心',7:r'计划|安排|明天',8:r'重新|继续做|没开始',9:r'约定|答应|承担',10:r'我.{0,12}(总是|经常|反复).{0,10}(担心|紧张)|想聊聊.{0,8}(担心|紧张)',11:r'我.{0,12}(总是|经常|反复).{0,10}(低落|难过)|想聊聊.{0,8}(失落|难过)',12:r'我.{0,12}(总是|经常|反复).{0,10}(生气|情绪)|想聊聊.{0,8}情绪',13:r'为什么|原因|读书|书',14:r'颜色|配色|照片|好看',15:r'组合|拼|创意'}
    for fact in facts:
        if fact.get('fact_ref')!='topics:optional':result.append(fact);continue
        choices=[c for c in fact['data']['candidates'] if re.search(patterns.get(int(c['id'].split('-')[1]),r'(?!)'),message)]
        if choices:
            card=choices[0]
            result.append({**fact,'data':{'candidate':{k:card[k] for k in ('id','scene','opening','exit','knowledge_precondition')},'rule':fact['data']['rule']}})
    return result
