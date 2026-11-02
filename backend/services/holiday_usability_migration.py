"""Retire interactions while preserving existing records."""
import json
from models import (WorldState, WorldCommitment, WorldEmergentEventRuntime,
                    WorldEventStage, WorldEventInstance, WorldAction, WorldAtomicActionExecution)

def retire_rope(db):
    return retire_activity(db, 'rope_practice', '绳结练习')


def retire_volley_match(db):
    return retire_activity(db, 'volley_match', '四人排球小场')


def retire_activity(db, recipe_id, label):
    from services.plan_service import _release_reservations
    from services.interaction_time_service import focus_state, _put_focus
    changed=0
    for world in db.query(WorldState).filter_by(world_version='chaoxi-holiday-v6').all():
        plans=db.query(WorldCommitment).filter_by(session_id=world.session_id,recipe_id=recipe_id).filter(
            WorldCommitment.status.in_(('proposed','accepted','in_progress'))).all()
        for plan in plans:
            reason='interaction_retired_usability_v6'
            plan.status='cancelled';plan.ended_reason_code=reason
            _release_reservations(db,plan=plan,reason_code=reason)
            runtime=db.query(WorldEmergentEventRuntime).filter_by(commitment_id=plan.id).first()
            if runtime:
                runtime.status='cancelled';runtime.terminal_reason_code=reason;runtime.revision+=1
                runtime.completed_day=world.current_day;runtime.completed_time_minutes=world.current_time_minutes
                meta=json.loads(runtime.metadata_json or '{}')
                if meta.get('experience'):
                    meta['experience'].update(status='cancelled',pending=None)
                runtime.metadata_json=json.dumps(meta,ensure_ascii=False)
                event=db.get(WorldEventInstance,runtime.event_instance_id)
                if event:event.status='cancelled'
                stage=db.query(WorldEventStage).filter_by(runtime_id=runtime.id).first()
                if stage and stage.status=='active':stage.status='failed';stage.outcome='not_completed';stage.revision+=1
                if (focus_state(world) or {}).get('runtime_id')==runtime.id:_put_focus(world,None)
            db.add(WorldAction(session_id=world.session_id,idempotency_key=f'retire-{recipe_id}-v6:{plan.id}',
                actor_type='system',action_type='interaction_retired',world_day=world.current_day,
                world_time_minutes=world.current_time_minutes,language='zh-CN',
                response_text=f'{label}已下架，未完成的安排已取消。',
                metadata_json=json.dumps({'plan_id':plan.id,'reason':reason})))
            changed+=1
        # Drop only future suggestions/jobs for the retired interaction.
        root=json.loads(world.state_json or '{}')
        jobs=root.get('scheduled_actions_v1',[])
        retired=[j for j in jobs if recipe_id=='rope_practice' and j.get('object_id')=='rope']
        for job in retired:
            audit=db.get(WorldAtomicActionExecution,job.get('audit_id')) if job.get('audit_id') else None
            if audit and audit.status=='scheduled':
                audit.status='failed';audit.reason_code='interaction_retired_usability_v6'
        if retired:root['scheduled_actions_v1']=[j for j in jobs if j not in retired]
        v5=root.get('holiday_v5',{})
        for key,value in list(v5.items()):
            if isinstance(value,dict):
                for sub,proposal in list(value.items()):
                    if isinstance(proposal,dict) and proposal.get('recipe_id')==recipe_id:
                        value.pop(sub)
        updated=json.dumps(root,ensure_ascii=False)
        if root!=json.loads(world.state_json or '{}'):world.state_json=updated
    db.flush()
    return changed
