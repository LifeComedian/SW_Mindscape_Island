"""Capture versioned interaction context."""
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from fastapi import HTTPException
from models import WorldCommitment, WorldPlanMember

VERSION = 'gameplay-evidence-v1'


def context(db, world, *, object_id=None):
    from services.atomic_action_service import list_atomic_action_candidates
    from services.interaction_time_service import focus_state
    from models import WorldEmergentEventRuntime
    focus = focus_state(world) or {}
    rid = focus.get('runtime_id')
    runtime = db.get(WorldEmergentEventRuntime, rid) if rid else None
    candidates = list_atomic_action_candidates(db, session_id=world.session_id, include_blocked=True)
    choices = [dict(action_id=c['action_id'], object_id=c['target']['object_id'],
                    available=c['available'], reason_code=c['reason_code'])
               for c in candidates['candidates'] if not object_id or c['target']['object_id'] == object_id]
    return dict(schema_version=VERSION, world_version=world.world_version,
                location_id=world.participant_location_id, day=world.current_day,
                minute=world.current_time_minutes, atomic_revision=candidates['revision'],
                runtime_id=rid, plan_id=runtime.commitment_id if runtime else None,
                choices=choices, eligibility_scope='atomic_preconditions_not_all_input_dependent_constraints')


def opportunity_context(db, world, body):
    result = context(db, world, object_id=body.target if body.kind in ('object', 'mechanism') else None)
    if body.kind == 'invitation':
        try:
            pid = int(body.target.removeprefix('plan:'))
        except ValueError:
            raise HTTPException(422, '邀约编号不正确。')
        plan = db.query(WorldCommitment).filter_by(id=pid, session_id=world.session_id).first()
        member = db.query(WorldPlanMember).filter_by(commitment_id=pid, actor_type='participant').first()
        if not plan or not member:
            raise HTTPException(404, '未找到属于本次会话的邀约。')
        result.update(plan_id=pid, plan_status=plan.status, response_status=member.response_status,
                      scheduled_day=plan.scheduled_day, scheduled_minute=plan.scheduled_time_minutes)
    registered = {c['action_id'] for c in result['choices']}
    if set(body.displayed_action_ids) - registered:
        raise HTTPException(422, '显示的动作不属于当前互动点。')
    result.update(client_reported_visible=True, client_reported_guided=body.guided,
                  client_reported_guidance_source=body.guidance_source,
                  client_reported_eligible=body.eligible, displayed_action_ids=body.displayed_action_ids,
                  eligible=any(c['available'] for c in result['choices']) if body.kind == 'object' else None,
                  visibility_verification='client_report_only', guidance_verification='client_report_only',
                  selection_outcome='not_inferred_from_view')
    return result


class TraceEvent(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    seq: int = Field(ge=1, le=100000)
    operation: Literal['add', 'move', 'remove', 'clear', 'style', 'polish', 'visit', 'restart', 'submit', 'rotate', 'copy', 'layer', 'undo']
    method: Literal['pointer', 'keyboard', 'button']
    piece_index: int | None = Field(default=None, ge=0, le=23)
    material: str | None = Field(default=None, pattern=r'^[a-zA-Z0-9_]+$', max_length=24)
    x: float | int | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    y: float | int | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    choice: str | None = Field(default=None, pattern=r'^[a-zA-Z0-9_]+$', max_length=24)


class WorkshopTrace(BaseModel):
    model_config = ConfigDict(extra='forbid')
    idempotency_key: str = Field(min_length=12, max_length=100)
    draft_id: str = Field(pattern=r'^[a-zA-Z0-9-]{12,64}$')
    object_id: Literal['flowers', 'wood_work', 'rope', 'beach']
    action_id: str = Field(pattern=r'^v4_(flowers|wood_work|rope|beach)__(make|walk|free)$')
    events: list[TraceEvent] = Field(min_length=1, max_length=32)
    dropped_count: int = Field(default=0, ge=0, le=100000)
    runtime_id: int | None = Field(default=None, ge=1)


def capture_trace(db, sid, body):
    from services.holiday_v5_service import binding, replay, ledger
    from services.world_service import session_write_lock
    from content.holiday_v4 import action_id
    from content.holiday_v6 import catalogue_for
    with session_write_lock(sid):
        db.rollback()
        request = body.model_dump()
        old = replay(db, sid, body.idempotency_key, request)
        if old is not None:
            return old
        world, spec = binding(db, sid, True)
        obj = catalogue_for(spec)[body.object_id]
        if obj['location_id'] != world.participant_location_id:
            raise HTTPException(409, '操作台已不在当前位置，不能把迟到的记录归入新场景。')
        if body.action_id not in {action_id(obj['id'], a['id']) for a in obj['actions']}:
            raise HTTPException(422, '操作台动作不匹配。')
        seq = [e.seq for e in body.events]
        if seq != sorted(set(seq)):
            raise HTTPException(422, '操作序号必须唯一且递增。')
        current = context(db, world, object_id=body.object_id)
        if current['runtime_id'] != body.runtime_id:
            raise HTTPException(409, '活动已切换，不能把之前的操作记录归入当前活动。')
        result = {**current, 'recorded': len(seq),
                  'draft_id': body.draft_id, 'source_quality': 'client_reported_trace_not_execution',
                  'completeness': 'partial' if body.dropped_count else 'not_guaranteed',
                  'does_not_advance_clock': True}
        row = ledger(db, world, body.idempotency_key, 'workshop_trace', request, result)
        result['source_action_id'] = row.id
        row.metadata_json = json.dumps({'request': request, 'result': result}, ensure_ascii=False)
        db.commit()
        return result
