"""Flexible work schedules subject to accepted plans and travel time."""
import json
from models import WorldAtomicActionExecution, CharacterState, WorldCommitment, WorldPlanMember
from services import scheduled_action_service as scheduled


def can_pause(db, world, job):
    from content.experience_next import enabled, VISITORS
    if enabled() and job.get('kind')=='routine_travel' and job.get('agent_id') in VISITORS and job.get('source')=='daily_schedule':
        return True
    if world.world_version not in ('chaoxi-holiday-v5', 'chaoxi-holiday-v6') or job['kind'] != 'atomic' or job.get('stage_runtime_id'):
        return False
    audit=db.query(WorldAtomicActionExecution).filter_by(id=job.get('audit_id'),session_id=world.session_id,status='scheduled').first()
    return bool(audit and json.loads(audit.metadata_json or '{}').get('interruptible'))


def pause_routine(db, world, agent_id, reason):
    values=scheduled.jobs(world)
    for job in values:
        if job['actor_key']!=f'resident:{agent_id}' or not can_pause(db,world,job):continue
        job['status']='cancelled'
        if job.get('kind')=='routine_travel':
            resident=db.query(CharacterState).filter_by(session_id=world.session_id,agent_id=agent_id).first()
            if resident:resident.current_activity='停下来聊聊'
            continue
        audit=db.get(WorldAtomicActionExecution,job['audit_id'])
        audit.status='cancelled';audit.reason_code=reason
        result=json.loads(audit.result_json or '{}')
        result.update(status='cancelled',execution_status='cancelled',reason_code=reason,effects=[])
        audit.result_json=json.dumps(result,ensure_ascii=False)
    scheduled._write(world,values)


def schedule_context(db,world,spec,agent_id):
    from world.schedules import resolve_resident_schedule
    from data.island import localized
    block=resolve_resident_schedule(spec,agent_id,world.current_day,world.current_time_minutes)
    busy=agent_id==4 and '饭点' in localized(block.activity,'zh-CN')
    return {'activity':localized(block.activity,'zh-CN'), 'workload':'meal_rush' if busy else 'flexible',
        'schedule_is_preference':True, 'may_take_break':True,
        'rule':'日程是可调整的个人打算。饭点通常较忙，其他工作可暂停；也允许自己选择在工作时休息或赴约。按性格、兴趣与已有承诺判断，不能把在工作当作必然拒绝。已接受的约定、共同行动和旅行必须遵守。'}


def preparing_for_plan(db,world,spec,resident):
    from services import plan_service as plans
    now=plans._ordinal(world.current_day,world.current_time_minutes)
    rows=db.query(WorldCommitment).join(WorldPlanMember,WorldPlanMember.commitment_id==WorldCommitment.id).filter(
        WorldCommitment.session_id==world.session_id,WorldCommitment.status.in_(('accepted','in_progress')),
        WorldPlanMember.actor_key==f'resident:{resident.agent_id}',WorldPlanMember.response_status=='accepted').all()
    for plan in rows:
        start=plans._ordinal(plan.scheduled_day,plan.scheduled_time_minutes)
        travel=plans._travel_minutes(spec,resident.current_location_id,plan.location_id)
        if travel is not None and start-travel-15<=now<start+plan.duration_minutes+(30 if __import__("content.experience_next",fromlist=["enabled"]).enabled() else 0):
            resident.current_activity='准备赴约' if resident.current_location_id!=plan.location_id else '在约定地点等候或参与活动'
            return True
    return False


def alternative_time(db,world,spec,plan,agent_id):
    from services import plan_service as plans
    actors=[{'actor_type':'resident','agent_id':agent_id,'actor_key':f'resident:{agent_id}','role_id':'guest','required':True}]
    if plan.organizer_type=='participant':actors.append({'actor_type':'participant','agent_id':None,'actor_key':'participant','role_id':'organizer','required':True})
    start=max(plan.scheduled_time_minutes+15,world.current_time_minutes+15) if plan.scheduled_day==world.current_day else plan.scheduled_time_minutes+15
    for minute in range(((start+4)//5)*5,min(start+150,spec.calendar.day_end_minute-plan.duration_minutes)+1,15):
        if agent_id==4 and (690<=minute<810 or 1050<=minute<1140):continue
        check=plans._availability(db,world=world,spec=spec,start_day=plan.scheduled_day,start_time_minutes=minute,
            duration_minutes=plan.duration_minutes,location_id=plan.location_id,actors=actors,
            object_ids=plans._json_loads(plan.object_ids_json,[]),role_slots=[],exclude_commitment_id=plan.id,allow_soft_jobs=True)
        if check['available']:return plan.scheduled_day,minute
    return None
