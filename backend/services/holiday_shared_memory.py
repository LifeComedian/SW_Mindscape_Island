"""Shared activity memories with source references and visibility checks."""
import json
import re
from models import Session, WorldAtomicActionExecution, WorldAction
from services.holiday_journal_facts import VERSION, completed_details, quoted_fragments, speech_sentence, render_details
from services.holiday_work_service import visible_works
RECALL_REQUEST=re.compile(r'(?:记得|记不记得|记起|想起|回忆).{0,24}(?:我们|咱们|一起)|(?:我们|咱们).{0,24}(?:记得|记不记得|一起做过)')

def collect(db,world,spec,runtime,plan,value,witnesses):
    session=db.get(Session,world.session_id)
    name=session.nickname if session else '新来的邻居'
    ids=[h['source_action_id'] for h in value['history'] if h['kind']=='action' and h.get('source_action_id')]
    executions=db.query(WorldAtomicActionExecution).filter(
        WorldAtomicActionExecution.session_id==world.session_id,
        WorldAtomicActionExecution.source_action_id.in_(ids),
        WorldAtomicActionExecution.status=='completed').all() if ids else []
    by_action={a['action_id']:a['label']['zh-CN'] for a in spec.systems['action_definitions']}
    observed=[{'source_action_id':a.source_action_id,'actor': 'participant' if a.actor_type=='participant' else f'resident:{a.actor_agent_id}',
               'action':by_action.get(a.action_id,a.action_id)} for a in executions]
    root=json.loads(world.state_json or '{}')
    records=root.setdefault('holiday_v6',{}).setdefault('shared_experiences',{})
    cards={}
    for person in witnesses:
        # Include only works created during this encounter.
        works=[w for w in visible_works(db,world,person['id']) if w['source_action_id'] in ids and w.get('design') and w['author']=='participant']
        details=completed_details(value['history'],{a.source_action_id:a for a in executions},name)
        for work in works[-1:]:
            from services.holiday_work_review import visible_features
            feature=visible_features(work)['visible_features']
            if work['object_id']=='flowers':
                details.append(f"{name}的桌花用了{feature['container']}，{feature.get('arrangement','')}")
            elif work['object_id']=='wood_work':
                materials='、'.join(m['name'] for m in feature.get('materials',[])[:2])
                details.append(f"{name}的木作里有{materials}" if materials else f"{name}带来一件木作")
        game=value.get('game') or {}
        if game.get('mode')=='uno':
            if game.get('finished') and game.get('winner'):
                winner=game.get('names',{}).get(game['winner'],game['winner'])
                if game['winner']=='participant':winner=name
                details.append(f"这局UNO是{winner}先出完手牌")
            else:details.append('一起玩了一会儿UNO')
        elif game.get('mode')=='volley-position' and game.get('done'):
            details.append(f"一起练了12次传接球，{name}接稳了{game['score']}次")
        if not details:
            participant_actions=[a['action'] for a in observed if a['actor']=='participant']
            # Fixed catalogue labels, no private message/card/reading text.
            details=[f"{name}完成了{participant_actions[-1]}"] if participant_actions else []
        spoken=quoted_fragments([h.get('text') for h in value['history'] if h.get('kind')=='dialogue' and h.get('speaker')=='你'],1)
        details.extend(speech_sentence(name,t) for t in spoken)
        dialogue_sources=[]
        for row in db.query(WorldAction).filter_by(session_id=world.session_id,actor_type='participant',action_type='activity_experience').order_by(WorldAction.id):
            meta=json.loads(row.metadata_json or '{}')
            if meta.get('runtime_id')==runtime.id and meta.get('request',{}).get('message') in spoken:dialogue_sources.append(row.id)
        card={'runtime_id':runtime.id,'recipe_id':plan.recipe_id,'participant_name':name,
              'day':getattr(runtime,'completed_day',None) or getattr(runtime,'started_day',None) or world.current_day,'location_id':plan.location_id,'public_details':details,
              'actions':observed,'source_action_ids':ids,'dialogue_source_ids':dialogue_sources,'version':VERSION}
        own=records.setdefault(str(person['id']),[])
        old=next((m for m in own if m['runtime_id']==runtime.id),None)
        if old is not None:old.update(card)
        else:
            own.append(card);records[str(person['id'])]=own[-20:]
        cards[person['id']]=card
    world.state_json=json.dumps(root,ensure_ascii=False)
    return cards

def public_post(card,agent_id,previous_count,title):
    name=card['participant_name']
    detail=render_details(card['public_details'][:4],name)
    # Describe familiarity through recorded repeat encounters.
    opening=f"今天又和{name}{title}。" if previous_count else f"今天和{name}{title}。"
    return opening+detail


def refresh_legacy(db,world):
    """Re-render only generated notes; keep post IDs, comments and action logs."""
    if world.world_version!='chaoxi-holiday-v6':return False
    from models import UserPost,WorldEmergentEventRuntime,WorldCommitment
    from world.registry import get_world_spec
    from data.island import localized
    spec=get_world_spec(world.world_version);changed=False
    for post in db.query(UserPost).filter_by(session_id=world.session_id,source_type='activity_experience',author_type='resident'):
        metadata=json.loads(post.facts_json or '{}')
        if metadata.get('journal_version')==VERSION:continue
        runtime=db.get(WorldEmergentEventRuntime,post.source_id)
        if not runtime or runtime.session_id!=world.session_id:continue
        value=json.loads(runtime.metadata_json or '{}').get('experience',{})
        plan=db.get(WorldCommitment,runtime.commitment_id)
        if not plan or value.get('status')!='completed' or post.author_agent_id not in spec.residents:continue
        title=next((localized(r['label'],'zh-CN') for r in spec.systems['activity_recipes'] if r['recipe_id']==plan.recipe_id),'待了一会儿')
        card=collect(db,world,spec,runtime,plan,value,[{'id':post.author_agent_id}])[post.author_agent_id]
        post.content=public_post(card,post.author_agent_id,0,title)
        post.facts_json=json.dumps({**metadata,'journal_version':VERSION,'narrative_status':'source_rendered',
            'shared_action_ids':card['source_action_ids'],'dialogue_source_ids':card['dialogue_source_ids']},ensure_ascii=False)
        changed=True
    return changed

def recall(world,spec,agent_id,message):
    """Explicit recall uses witnessed cards, not guessed completion prose."""
    if not RECALL_REQUEST.search(message):
        return None
    cards=json.loads(world.state_json or '{}').get('holiday_v6',{}).get('shared_experiences',{}).get(str(agent_id),[])
    from services.holiday_guidance_v6 import topic
    object_topic=topic(message)
    recipe={'flowers':'flower_arranging','wood_work':'woodcraft','games':'table_game','volleyball':'volley_pass',
            'books':'reading','postcards':'postcard','beach':'beach_search'}.get(object_topic)
    if recipe:cards=[card for card in cards if card['recipe_id']==recipe]
    # Don't answer a specific older date using a more recent encounter.
    day=re.search(r'第([1-7])天',message)
    if day:cards=[card for card in cards if card['day']==int(day[1])]
    if not cards:return None
    card=cards[-1]
    location=spec.locations[card['location_id']].name['zh-CN']
    activity=next((r['label']['zh-CN'] for r in spec.systems['activity_recipes'] if r['recipe_id']==card['recipe_id']),'待了一会儿')
    when='今天' if card['day']==world.current_day else f"第{card['day']}天"
    detail='；'.join(card['public_details'][:2]).replace(card['participant_name'],'你')
    return {'text':f"记得，{when}我们在{location}{activity}。{detail}。",
            'runtime_id':card['runtime_id'],'source_action_ids':card['source_action_ids']}
