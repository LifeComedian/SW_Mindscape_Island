"""Saved works and visibility-filtered resident observations."""
from copy import deepcopy
import json
from models import CharacterState, WorldAction, WorldAtomicActionExecution


def all_works(world):
    actors=json.loads(world.state_json or '{}').get('modular_runtime',{}).get('object_states',{}).get('_v4',{}).get('actors',{})
    return [dict(w,author=actor) for actor,own in actors.items() for w in own.get('works',[]) if w.get('work_id')]


def attach_sources(world, action, actor_key):
    if world.world_version != 'chaoxi-holiday-v6':return
    root=json.loads(world.state_json or '{}')
    own=root.get('modular_runtime',{}).get('object_states',{}).get('_v4',{}).get('actors',{}).get(actor_key,{})
    for index,work in enumerate(own.get('works',[])):
        if work.get('source_action_id') or work.get('object_id') != action.target_object_id:continue
        work.update(work_id=f'work:{action.id}:{index}',source_action_id=action.id,author=actor_key,
                    location_id=action.target_location_id,minute=action.world_time_minutes,
                    visibility=work.get('visibility','scene_public' if work.get('design') or work.get('strokes') else 'private'))
    world.state_json=json.dumps(root,ensure_ascii=False)


def visible_works(db,world,agent_id=None,*,location_id=None):
    actor=db.query(CharacterState).filter_by(session_id=world.session_id,agent_id=agent_id).first() if agent_id else None
    location=location_id or (actor.current_location_id if actor else world.participant_location_id)
    works=[]
    for work in all_works(world):
        if work.get('visibility') not in ('scene_public','island_public') or work.get('location_id')!=location:continue
        executed=db.query(WorldAtomicActionExecution.id).filter_by(session_id=world.session_id,
            source_action_id=work['source_action_id'],status='completed').first()
        if executed:works.append(work)
    return works[-24:]


def work_facts(db,world,agent_id):
    now=visible_works(db,world,agent_id)
    remembered=json.loads(world.state_json or '{}').get('holiday_v6',{}).get('observed_works',{}).get(str(agent_id),{})
    facts=[dict(w,perception='previously_seen') for w in remembered.values() if w['work_id'] not in {x['work_id'] for x in now}]
    return [*facts[-8:],*[dict(w,perception='visible_here') for w in now]][-24:]


def authored_exhibits(db,world,agent_id):
    """Fixed public displays at the resident's actual location, not player acts."""
    from content.holiday_v6 import catalogue_for
    actor=db.query(CharacterState).filter_by(session_id=world.session_id,agent_id=agent_id).first()
    if not actor:return []
    return [dict(object_id=obj['id'],id=item['id'],title=item['name'],text=item['text'],
                 source_type='authored_exhibit',perception='visible_here')
            for obj in catalogue_for(world).values() if obj['location_id']==actor.current_location_id
            for act in obj['actions'] if act['id'] in ('browse','album','read')
            for item in act['items']]


def remember_observed(world,agent_id,works):
    if world.world_version!='chaoxi-holiday-v6' or not works:return
    root=json.loads(world.state_json or '{}')
    records=root.setdefault('holiday_v6',{}).setdefault('observed_works',{}).setdefault(str(agent_id),{})
    for work in works:
        if work.get('perception')=='visible_here':
            records[work['work_id']]={k:deepcopy(v) for k,v in work.items() if k!='perception'}
    root['holiday_v6']['observed_works'][str(agent_id)]=dict(list(records.items())[-24:])
    world.state_json=json.dumps(root,ensure_ascii=False)


def select_work(message,works):
    visible=[w for w in works if w.get('perception')=='visible_here' and w.get('author')=='participant']
    kinds=[('木船','wood_work'),('木工','wood_work'),('木作','wood_work'),('插花','flowers'),('桌花','flowers'),('速写','sketch'),('明信片','postcards')]
    oid=next((oid for word,oid in kinds if word in message),None)
    candidates=[w for w in visible if not oid or w['object_id']==oid]
    exact=[w for w in candidates if w['work_id'] in message or w['title'] in message]
    if len(exact)==1:return exact[0]
    if candidates and any(t in message for t in ('刚刚做的','刚做的','刚才做的','最新的','最新做的','最新完成的','刚刚完成的','最后做的')):
        return max(candidates,key=lambda w:w['source_action_id'])
    return candidates[-1] if len(candidates)==1 else None


def gallery(db,world,object_id):
    origin={'wood_display':'wood_work','flowers':'flowers','sketch':'sketch','postcards':'postcards'}.get(object_id)
    if not origin:return []
    return [dict(id=w['work_id'],name=w['title'],text=w.get('text','你保存的速写线条。'),design=w.get('design'),
                 strokes=w.get('strokes'),stroke_styles=w.get('stroke_styles'),day=w['day'],author=w['author'],source_action_id=w['source_action_id'],
                 source_type='completed_atomic_action',art_id=w.get('art_id'))
            for w in visible_works(db,world) if w['object_id']==origin]


def factual_description(work):
    author='你' if work['author']=='participant' else '对方'
    return f"{author}的《{work['title']}》："+work.get('text','这份作品保留着实际保存的线条。').replace('你',author)
