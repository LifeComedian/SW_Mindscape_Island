"""Holiday daily anchors plus duration-bearing resident trips chosen by the gateway."""
import json
from models import WorldAction, CharacterState
from services import scheduled_action_service as jobs, plan_service as plans
from world.graph import shortest_travel_path
from world.schedules import resolve_resident_schedule
from data.island import localized


def start_trip(db, *, world, spec, resident, destination, key, source, schedule):
    if db.query(WorldAction.id).filter_by(session_id=world.session_id, idempotency_key=key).first():
        return False
    if jobs.actor_busy(world, f"resident:{resident.agent_id}"):
        return False
    path = shortest_travel_path(spec, resident.current_location_id, destination)
    if not path or len(path) < 2:
        return False
    now = plans._ordinal(world.current_day, world.current_time_minutes)
    duration = (len(path)-1) * int(spec.action_minutes['move'])
    if world.current_time_minutes + duration > spec.calendar.day_end_minute:
        return False
    job = dict(job_id=key, kind="routine_travel", status="pending", actor_key=f"resident:{resident.agent_id}", agent_id=resident.agent_id,
        start_ordinal=now, end_ordinal=now+duration, location_id=resident.current_location_id, destination=destination, path=list(path), schedule_id=schedule.state_id, source=source)
    jobs._write(world, [*jobs.jobs(world), job])
    state = json.loads(resident.state_json or '{}')
    state.update(last_schedule_day=world.current_day, autonomy_schedule_override_state=schedule.state_id, last_trip_ordinal=now)
    resident.schedule_state = schedule.state_id
    resident.current_activity = '正在前往' + localized(spec.locations[destination].name, 'zh-CN')
    resident.state_json = plans._json_dumps(state)
    db.add(WorldAction(session_id=world.session_id, idempotency_key=key, actor_type='resident', actor_agent_id=resident.agent_id,
        action_type='resident_depart', target_location_id=destination, world_day=world.current_day, world_time_minutes=world.current_time_minutes, metadata_json=plans._json_dumps(job), response_text='', language='zh-CN'))
    db.flush()
    return True


def sync_routine(db, *, world, spec, resident):
    schedule = resolve_resident_schedule(spec, resident.agent_id, world.current_day, world.current_time_minutes)
    state = json.loads(resident.state_json or '{}')
    if state.get('last_schedule_day') != world.current_day:
        # The overnight transition is outside the playable day.
        resident.current_location_id = spec.residents[resident.agent_id].home_location_id
        from content.experience_next import enabled, VISITORS
        if enabled() and resident.agent_id in VISITORS and world.current_day==VISITORS[resident.agent_id][0]:
            resident.current_location_id='loc_01'
        state.update(last_schedule_day=world.current_day)
        state.pop('autonomy_schedule_override_state', None)
        resident.state_json = plans._json_dumps(state)
    if jobs.actor_busy(world, f'resident:{resident.agent_id}'):
        return
    if plans.resident_is_in_active_plan(db, session_id=world.session_id, agent_id=resident.agent_id, location_id=resident.current_location_id):
        return
    # Accepted plans override the normal work schedule.
    if spec.world_version in ('chaoxi-holiday-v5', 'chaoxi-holiday-v6'):
        from services.holiday_flex_service import preparing_for_plan
        if preparing_for_plan(db,world,spec,resident):return
    if state.get('autonomy_schedule_override_state') == schedule.state_id:
        return
    if resident.current_location_id != schedule.location_id:
        start_trip(db, world=world, spec=spec, resident=resident, destination=schedule.location_id,
            key=f'routine:{world.current_day}:{resident.agent_id}:{schedule.state_id}:{world.current_time_minutes}', source='daily_schedule', schedule=schedule)
    else:
        resident.schedule_state = schedule.state_id
        resident.current_activity = localized(schedule.activity, 'zh-CN')
        resident.current_goal = localized(schedule.goal, 'zh-CN')


def travel_options(db, world, spec, actor, schedule):
    flexible = spec.world_version in ('chaoxi-holiday-v3', 'chaoxi-holiday-v4', 'chaoxi-holiday-v5', 'chaoxi-holiday-v6') and world.current_time_minutes >= 570
    if not spec.world_version.startswith('chaoxi-holiday-') or not flexible and '自由时间' not in localized(schedule.activity, 'zh-CN'):
        return []
    row = db.query(CharacterState).filter_by(session_id=world.session_id, agent_id=actor.agent_id).one()
    now = plans._ordinal(world.current_day, world.current_time_minutes)
    if now - json.loads(row.state_json or '{}').get('last_trip_ordinal', -1000) < 30:
        return []
    options = []
    for lid, place in spec.locations.items():
        if lid in (actor.location_id, 'guest_room', 'residential'):
            continue
        path = shortest_travel_path(spec, actor.location_id, lid)
        duration = (len(path)-1) * int(spec.action_minutes['move']) if path else 999
        if world.current_time_minutes + duration + 15 > schedule.end_minute:
            continue
        available = plans._availability(db, world=world, spec=spec, start_day=world.current_day, start_time_minutes=world.current_time_minutes + (duration if flexible else 0),
            duration_minutes=15 if flexible else duration+15, location_id=lid, actors=[{'actor_type': 'resident', 'agent_id': actor.agent_id, 'actor_key': actor.actor_key, 'role_id': None, 'required': True}], object_ids=[], role_slots=[])
        if available['available']:
            options.append((lid, f"去{localized(place.name, 'zh-CN')}自由活动，路程约{duration}分钟，再停留至少15分钟。"))
    return options
