"""Publish stable daily choices using only the corresponding owner's prior-day chat."""
import json,re
from copy import deepcopy
from content.experience_next import enabled, VERSION
from content.experience_next_stock import libraries,OWNERS,COUNTS,flower_materials
from content.experience_next_catalogue import EXTRAS
from models import WorldAction

def all_choices():
    from content.holiday_v6 import base_catalogue
    return libraries(base_catalogue(),EXTRAS)

def publish(db,world,day):
    if not enabled():return
    root=json.loads(world.state_json or '{}');state=root.setdefault('island_next',{'version':VERSION,'days':{}})
    if str(day) not in state['days']:
        decisions={}
        for key,items in all_choices().items():
            actor=OWNERS[key]
            messages=db.query(WorldAction).filter(WorldAction.session_id==world.session_id,WorldAction.actor_type=='participant',
                WorldAction.target_agent_id==actor,WorldAction.action_type.in_(('conversation_message','private_message','phone_comment')),WorldAction.world_day==day-1).order_by(WorldAction.id.desc()).limit(80).all()
            for row in messages:
                text=row.response_text or ''
                if re.search(r'都喜欢|随便|如果|他说|她说',text):continue
                negative=bool(re.search(r'不喜欢|不想|不要|不爱',text))
                if not negative and not re.search(r'我.{0,6}(喜欢|想喝|想吃|爱吃|想要|想看|想读)|明天.{0,8}(能不能|可以|想)',text):continue
                mentioned=[i for i in items if any(t in text for t in [i['name'].split('》')[0].lstrip('《'),*i.get('tags',[])])]
                mentioned.sort(key=lambda i:(i['name'].split('》')[0].lstrip('《') not in text,-max([len(t) for t in i.get('tags',[]) if t in text] or [0])))
                match=next((i for i in items if i not in mentioned),None) if negative and mentioned else (mentioned[0] if mentioned and not negative else None)
                if match:
                    decisions[key]={'item_id':match['id'],'reason':'player_preference','source_ref':'A'+str(row.id),'owner_id':actor,'status':'published','day':day,'excluded_ids':[i['id'] for i in mentioned] if negative else []}
                    decisions[key]['item_ids']=[match['id']] if negative else [i['id'] for i in mentioned[:COUNTS[key]]]
                    db.add(WorldAction(session_id=world.session_id,idempotency_key=f'next-catalogue:{day}:{key}',actor_type='resident',actor_agent_id=actor,action_type='daily_catalogue_published',world_day=day,world_time_minutes=world.current_time_minutes,language='zh-CN',response_text=match['name'],metadata_json=json.dumps({'item':match['name'],'source_ref':'A'+str(row.id),'object_id':key,'owner_id':actor,'status':'published'},ensure_ascii=False)))
                    break
        state['days'][str(day)]={'version':VERSION,'decisions':decisions}
        world.state_json=json.dumps(root,ensure_ascii=False)
    from services.experience_next_postcard_service import ensure_visitors
    ensure_visitors(db,world)

def apply(world,catalogue):
    if not enabled() or not hasattr(world,'state_json'):return catalogue
    state=json.loads(world.state_json or '{}').get('island_next',{}).get('days',{}).get(str(world.current_day),{})
    choices=all_choices()
    for key,decision in state.get('decisions',{}).items():
        item=next((i for i in choices.get(key,[]) if i['id']==decision['item_id']),None)
        if item:
            for action in catalogue[key]['actions']:
                if action['id'] in ('browse','album','read','order'):
                    count=len(action['items']);excluded=set(decision.get('excluded_ids',[]))
                    requested=decision.get('item_ids',[item['id']])
                    selected=[deepcopy(i) for item_id in requested for i in choices[key] if i['id']==item_id and i['id'] not in excluded]
                    selected += [i for i in action['items'] if i['id'] not in requested and i['id'] not in excluded]
                    selected += [deepcopy(i) for i in choices[key] if i['id'] not in excluded and i['id'] not in {x['id'] for x in selected}]
                    action['items']=selected[:count]
    flower_materials(catalogue['flowers'])
    from services.experience_next_postcard_service import apply_catalogue
    apply_catalogue(world,catalogue)
    return catalogue
