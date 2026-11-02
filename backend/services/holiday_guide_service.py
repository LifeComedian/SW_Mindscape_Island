"""Orientation prompts based on recorded events."""
from models import WorldAction, UserPost, WorldPlanMember, WorldCommitment
from services import plan_service as plans


def guides(db, sid):
    try:
        world, spec = plans._world_and_spec(db, sid)
    except plans.PlanServiceError as exc:
        if exc.reason_code in ('world_ended','session_inactive'):
            return {'guides': [], 'exploration': [], 'optional': True}
        from fastapi import HTTPException
        raise HTTPException(exc.status_code, str(exc)) from exc
    if spec.world_version not in ('chaoxi-holiday-v3', 'chaoxi-holiday-v4', 'chaoxi-holiday-v5', 'chaoxi-holiday-v6'):
        return {'guides': []}
    if spec.world_version in ('chaoxi-holiday-v5', 'chaoxi-holiday-v6'):
        return v5_guides(db, sid, spec)
    rows = db.query(WorldAction).filter_by(session_id=sid, actor_type='participant').all()
    import json
    talked = {r.target_agent_id for r in rows if r.action_type == 'conversation_message' and r.target_agent_id}
    for row in rows:
        if row.action_type == 'activity_experience':
            request = json.loads(row.metadata_json or '{}').get('request', {})
            if request.get('operation') in ('chat', 'suggest') and request.get('speaker_id'):
                talked.add(request['speaker_id'])
    places = {r.target_location_id for r in rows if r.action_type == 'move' and r.target_location_id}
    entries = [
        ('neighbors', '认识岛上的邻居', '岛上住着八位邻居。路过时打个招呼，听听他们各自的故事。', len(talked), len(spec.residents)),
        ('phone', '看看岛上的新鲜事', '手机里有邻居的动态，也有约大家一起做事的邀请。', int(any(r.action_type == 'holiday_phone_open' for r in rows)), 1),
        ('visit', '沿着小路走一走', '挑两个想去的地方，熟悉客房外的街巷。', len(places), 2),
        ('object', '试试这里的玩法', '翻翻桌上的东西，试试一件让你感兴趣的小事。', int(any(r.action_type in ('atomic_action','defined_action') for r in rows)), 1),
        ('post', '发一条动态', '把今天的一点见闻发到动态里，让邻居也看看。', int(db.query(UserPost.id).filter_by(session_id=sid, author_type='participant', post_type='personal').first() is not None), 1),
        ('invite', '约人一起玩', '有想一起做的事？在手机里选好地方和时间，问问谁有空。', int(db.query(WorldCommitment.id).filter_by(session_id=sid, organizer_type='participant').first() is not None), 1),
        ('accept', '看看收到的邀请', '遇到感兴趣的邀约，答应下来，记得按约定去见面。', int(db.query(WorldPlanMember.id).join(WorldCommitment,WorldCommitment.id==WorldPlanMember.commitment_id).filter(WorldCommitment.session_id==sid,WorldCommitment.organizer_type=='resident',WorldPlanMember.actor_key=='participant',WorldPlanMember.response_status=='accepted').first() is not None), 1),
    ]
    # Intro first, then the social opportunities. Previously completed actions count.
    visible = entries if world.current_day > 1 or sum(min(n,t) for _,_,_,n,t in entries[:4]) >= 3 else entries[:4]
    return {'guides': [{'id':k,'title':title,'detail':detail,'progress':min(n,total),'total':total} for k,title,detail,n,total in visible]}


def phone_open(db, sid):
    from services.world_service import session_write_lock, world_has_ended
    with session_write_lock(sid):
        db.rollback()
        world, spec = plans._world_and_spec(db, sid)
        key='holiday-phone-introduction'
        if spec.world_version in ('chaoxi-holiday-v3', 'chaoxi-holiday-v4', 'chaoxi-holiday-v5', 'chaoxi-holiday-v6') and not world_has_ended(world) and not db.query(WorldAction.id).filter_by(session_id=sid,idempotency_key=key).first():
            db.add(WorldAction(session_id=sid,idempotency_key=key,actor_type='participant',action_type='holiday_phone_open',
                language='zh-CN',world_day=world.current_day,world_time_minutes=world.current_time_minutes,metadata_json='{}'))
            db.commit()
    return {'ok':True}


def v5_guides(db, sid, spec):
    import json
    from content.experience_next import enabled
    if enabled():
        from services.experience_next_guides import guides as next_guides
        return next_guides(db,sid,spec)
    rows=db.query(WorldAction).filter_by(session_id=sid,actor_type='participant').all()
    seen={json.loads(r.metadata_json).get('request',{}).get('target') for r in rows if r.action_type=='opportunity_seen' and json.loads(r.metadata_json).get('request',{}).get('kind')=='guidebook'}
    def item(key,title,detail,n,total):
        return {'id':key,'title':title,'detail':detail,'progress':min(n,total),'total':total}
    if 'opened' not in seen:
        return {'guides':[item('book','先翻开岛屿介绍册','客房床头放着介绍册。打开它，先认识这座岛。',0,1)]}
    chapters={'places','residents','play'}
    if not chapters <= seen:
        return {'guides':[item('book_read','认识小岛、居民和玩法','介绍册分为地点、居民和玩法三章。想看哪章就点哪章，也可以关上以后再看。',len(chapters&seen),3)]}
    talked={r.target_agent_id for r in rows if r.action_type=='conversation_message' and r.target_agent_id}
    places={r.target_location_id for r in rows if r.action_type=='move'}
    definitions=[r for r in rows if r.action_type in ('atomic_action','defined_action')]
    missing='、'.join(r.name for aid,r in spec.residents.items() if aid not in talked)
    mechanisms={json.loads(r.metadata_json).get('request',{}).get('target') for r in rows if r.action_type=='opportunity_seen' and json.loads(r.metadata_json).get('request',{}).get('kind')=='mechanism'}
    attempts=db.query(WorldCommitment.id).filter_by(session_id=sid,organizer_type='participant').first()
    entries=[item('first_walk','选一处地方走走','在地图上选个想去的地方，看看那里能做什么。',int(bool(places))+int(bool(definitions)),2),
             item('neighbors','认识岛上的邻居','路过时打个招呼。还没认识：'+(missing or '已经认识了所有邻居。'),len(talked),8),
             item('visit','沿着小路探索','想去哪儿都可以。去过的地方会记在清单里。',len(places|{'guest_room'}),len(spec.locations)),
             item('mechanism','看看多人玩法','物品窗口会介绍单人和多人玩法。看看人数要求，再决定要不要邀请别人。',int(bool(mechanisms)),1),
             item('invite','约人一起玩','可以当面约，也可以用手机私信或邀约页。对方可能答应、婉拒或另约时间。',int(bool(attempts) or any(r.action_type in ('dialogue_plan_confirmation','private_message') and 'reject' in r.metadata_json for r in rows)),1)]
    preferred=[e for e in entries if e['progress']<e['total']][:2]
    return {'guides':preferred,'exploration':entries,'optional':True}
