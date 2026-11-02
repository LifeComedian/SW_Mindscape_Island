"""Versioned opening hours and explicit day-boundary acknowledgement."""
import json

VERSION='chaoxi-holiday-v6'
HOURS={
    'loc_01':[(480,1320)],'loc_02':[(540,1200)],'loc_03':[(480,1260)],
    'loc_04':[(660,840),(1020,1260)],'loc_05':[(480,1320)],
    'loc_06':[(480,1260)],'residential':[(480,1320)],'guest_room':[(480,1320)],
}
OWNERS={'restaurant':4,'cafe':6}


def hours_text(location_id):
    return '、'.join(f'{a//60:02d}:{a%60:02d}–{b//60:02d}:{b%60:02d}' for a,b in HOURS.get(location_id,[(480,1320)]))


def is_open(location_id,minute,duration=0):
    return any(a<=minute<b and minute+duration<=b for a,b in HOURS.get(location_id,[(480,1320)]))


def pending(world):
    return (world.world_version==VERSION and world.current_time_minutes>=1320
        and not json.loads(world.state_json or '{}').get('holiday_v6',{}).get('departure_confirmed'))


def require_awake(world):
    if pending(world):
        from services.world_service import WorldStateError
        raise WorldStateError('今天已经结束，请先在过场画面确认下一天。',409)


def venue_available(db,world,venue):
    from models import CharacterState
    lid={'restaurant':'loc_04','cafe':'loc_06'}[venue]
    if not is_open(lid,world.current_time_minutes):return False,'已打烊，目前只能查看菜单。'
    owner=db.query(CharacterState).filter_by(session_id=world.session_id,agent_id=OWNERS[venue]).first()
    if not owner or owner.current_location_id!=lid:return False,'老板暂时不在，目前只能查看菜单。'
    return True,''


def location_status(world,location_id):
    minute=world.current_time_minutes
    closing=next((b for a,b in HOURS.get(location_id,[]) if a<=minute<b),None)
    return {'hours':hours_text(location_id),'open':is_open(location_id,minute),
            'closing_in':closing-minute if closing is not None else None}


def invitation_slots(db,world,spec,recipe_id,day,agent_ids=()):
    """Read-only preview using the same availability validator as confirmation."""
    from services import plan_service as plans
    recipe=plans._recipe(spec,recipe_id)
    if recipe.get('retired') or not world.current_day<=day<=spec.calendar.total_days:
        return []
    agents=sorted(set(agent_ids))
    if any(a not in spec.residents for a in agents):return []
    actors=plans._normalize_actor_refs([{'actor_type':'participant'},*[{'actor_type':'resident','agent_id':a} for a in agents]])
    earliest=max(480,world.current_time_minutes+15) if day==world.current_day else 480
    times=[]
    for minute in range(((earliest+4)//5)*5,1320,5):
        if not is_open(recipe['location_ids'][0],minute,recipe['duration_minutes']):continue
        try:
            available=plans._availability(db,world=world,spec=spec,start_day=day,start_time_minutes=minute,
                duration_minutes=recipe['duration_minutes'],location_id=recipe['location_ids'][0],
                actors=actors,object_ids=list(recipe['object_ids']),role_slots=[],allow_soft_jobs=True)
            if available['available']:times.append(minute)
        except plans.PlanServiceError:continue
    return times


def acknowledge(db,sid,body):
    from services.holiday_v5_service import binding,replay,ledger
    from services.world_service import session_write_lock,_advance_to_next_day
    from fastapi import HTTPException
    request=body.model_dump()
    with session_write_lock(sid):
        db.rollback()
        old=replay(db,sid,body.idempotency_key,request)
        if old is not None:return old
        world,spec=binding(db,sid)
        if world.world_version!=VERSION or not pending(world) or world.current_day!=body.day:
            raise HTTPException(409,'日期已变化，请刷新过场画面。')
        if world.current_day==spec.calendar.total_days:
            root=json.loads(world.state_json or '{}')
            root.setdefault('holiday_v6',{})['departure_confirmed']=True
            world.state_json=json.dumps(root,ensure_ascii=False)
        else:
            # Day jumps only here, after an explicit versioned command.
            _advance_to_next_day(db,world)
            world.participant_location_id='guest_room'
            from services.experience_next_daily import publish
            publish(db,world,world.current_day)
        result={'day':world.current_day,'minute':world.current_time_minutes,'pending':pending(world)}
        ledger(db,world,body.idempotency_key,'day_transition_confirmed',request,result)
        db.commit()
        return result
