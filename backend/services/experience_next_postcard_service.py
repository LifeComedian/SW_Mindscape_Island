"""Finite postcard faces; allocation and quotas use the atomic world transaction."""
import json
from copy import deepcopy
from content.experience_next import enabled
from content.experience_next_postcards import INITIAL,FACES,VISITORS
from content.experience_next_stock import sample
from models import WorldAction,Session
from services.holiday_journal_facts import quoted_fragments,speech_sentence,render_details

TEXT_VERSION='visitor-journal-v2'

def actors(world):
    return json.loads(world.state_json or '{}').get('modular_runtime',{}).get('object_states',{}).get('_v4',{}).get('actors',{})

def visitor_cards(world):
    return json.loads(world.state_json or '{}').get('island_next',{}).get('visitor_postcards',{})

def remaining(world,states=None):
    states=actors(world) if states is None else states
    used={p['id'] for p in INITIAL}|{p['face_id'] for p in visitor_cards(world).values()}
    used.update(w.get('face_id') for own in states.values() for w in own.get('works',[]) if w.get('object_id')=='postcards')
    return [deepcopy(p) for p in FACES if p['id'] not in used]

def status(world,states=None,actor='participant'):
    states=actors(world) if states is None else states
    written=any(w.get('object_id')=='postcards' and w.get('day')==world.current_day for w in states.get(actor,{}).get('works',[]))
    written=written or any(p.get('author')==actor and p.get('day')==world.current_day for p in visitor_cards(world).values())
    choices=remaining(world,states)
    return {'written_today':written,'can_write':not written and bool(choices),'remaining':len(choices),'faces':choices}

def save_face(world,states,actor,payload):
    from services.holiday_object_service import fail
    available=status(world,states,actor)
    if available['written_today']:fail('今天已经写过一张明信片了，明天再来写吧。')
    if not available['faces']:fail('这次旅行的明信片已经用完了。')
    face=next((p for p in available['faces'] if p['id']==payload.get('face_id')),None)
    if not face:fail('请选择一张尚未使用的明信片；卡片状态变化时请重新加载。')
    return {'face_id':face['id'],'art_id':face['art_id'],'title':'明信片 · '+face['name']}

def _message(db,world,aid,day):
    session=db.get(Session,world.session_id)
    name=session.nickname if session else '岛上的邻居'
    lines=[];sources=[]
    shared=json.loads(world.state_json or '{}').get('holiday_v6',{}).get('shared_experiences',{}).get(str(aid),[])
    places={'loc_01':'沙滩与码头','loc_02':'花坊与木作间','loc_03':'零食店','loc_04':'餐馆','loc_05':'公共广场','loc_06':'咖啡馆','guest_room':'民宿'}
    activities={'meal':'一起吃饭','coffee':'一起喝东西','woodcraft':'一起做木作','flower_arranging':'一起插花','reading':'一起看书','table_game':'一起玩桌游','postcard':'一起写明信片','volley_pass':'一起练传球'}
    encounters=[s for s in shared if day-1<=s.get('day',0)<day]
    for card in encounters[-2:]:
        place=places.get(card.get('location_id'),'岛上')
        lines.append('和'+name+'在'+place+activities.get(card.get('recipe_id'),'待了一会儿')+'。')
        details=card.get('public_details',[])
        # Old generic labels are not a substitute for an actual travel record.
        details=[s for s in details if '试了用餐' not in s and '完成了用餐' not in s]
        if details:lines.append(render_details(details[:4],name))
        sources.extend(card.get('source_action_ids',[])+card.get('dialogue_source_ids',[]))
    messages=db.query(WorldAction).filter(WorldAction.session_id==world.session_id,WorldAction.target_agent_id==aid,
        WorldAction.actor_type=='participant',WorldAction.world_day==day-1,
        WorldAction.action_type=='conversation_message').order_by(WorldAction.id).all()
    import re
    available=[r.response_text for r in messages if not(encounters and re.search(r'有空|一起.{0,8}(吃|喝|饭)|几点|约.{0,5}(饭|餐)',r.response_text or ''))]
    spoken=quoted_fragments(available,1 if encounters else 2)
    for text in spoken:
        if text in ''.join(lines):continue
        lines.append('和'+name+'聊天时，'+speech_sentence(name,text)+'。')
        sources.extend(r.id for r in messages if r.response_text==text)
    own=db.query(WorldAction).filter(WorldAction.session_id==world.session_id,WorldAction.actor_type=='resident',
        WorldAction.actor_agent_id==aid,WorldAction.world_day==day-1).order_by(WorldAction.id.desc()).all()
    visits=[]
    for row in reversed(own):
        arrived=row.action_type in ('move','routine_arrival') or row.action_type=='resident_arrival' and json.loads(row.metadata_json or '{}').get('status')=='completed'
        if row.target_location_id in places and arrived and (not visits or row.target_location_id!=visits[-1].target_location_id):visits.append(row)
    if visits:
        periods={}
        for row in visits:
            minute=row.world_time_minutes or 0
            phase='上午' if minute<720 else '下午' if minute<1020 else '傍晚' if minute<1140 else '晚上'
            periods.setdefault(phase,[]).append(row)
        selected=[];route=[]
        for phase,arrivals in periods.items():
            pair=[arrivals[0]]+([arrivals[-1]] if arrivals[-1].target_location_id!=arrivals[0].target_location_id else [])
            selected.extend(pair)
            route.append(phase+'去了'+places[pair[0].target_location_id]+('，后来到'+places[pair[1].target_location_id] if len(pair)>1 else '')+'。')
        lines.insert(0,'昨天'+''.join(route))
        sources.extend(r.id for r in selected)
    if not lines:lines=['这是我在岛上的第二天，留下一张明信片。']
    basis='shared_activity' if encounters else 'conversation' if spoken else 'activity' if visits else 'current_postcard'
    return '\n\n'.join(lines),list(dict.fromkeys(sources)),basis

def ensure_visitors(db,world):
    if not enabled() or world.world_version!='chaoxi-holiday-v6':return False
    from services.holiday_shared_memory import refresh_legacy
    changed=refresh_legacy(db,world)
    for aid,(day,name) in VISITORS.items():
        if day>world.current_day:continue
        existing=visitor_cards(world).get(str(aid))
        if existing and existing.get('text_version')==TEXT_VERSION:continue
        choices=remaining(world)
        if not choices and not existing:continue
        face=next((f for f in FACES if existing and f['id']==existing['face_id']),None) or sample(choices,world.session_id,day,'visitor-card:'+str(aid),1)[0]
        text,sources,basis=_message(db,world,aid,day)
        card={'id':'visitor_card_'+str(aid),'name':name+'的明信片','text':text+'\n\n——'+name,
              'day':day,'author':'resident:'+str(aid),'source_type':'visitor_postcard','face_id':face['id'],
              'art_id':face['art_id'],'source_action_ids':sources,'content_basis':basis,'text_version':TEXT_VERSION}
        root=json.loads(world.state_json or '{}')
        root.setdefault('island_next',{}).setdefault('visitor_postcards',{})[str(aid)]=card
        world.state_json=json.dumps(root,ensure_ascii=False);changed=True
    return changed

def apply_catalogue(world,catalogue):
    action=next(a for a in catalogue['postcards']['actions'] if a['id']=='browse')
    action['items']=deepcopy(INITIAL)+[deepcopy(p) for p in visitor_cards(world).values() if p['day']<=world.current_day]
    write=next(a for a in catalogue['postcards']['actions'] if a['id']=='write')
    available=status(world)
    write['items']=available['faces']
    write['postcard_status']={k:v for k,v in available.items() if k!='faces'}
