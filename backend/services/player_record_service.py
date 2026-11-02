"""Participant travel notes with per-record visibility."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from database import Base
from services import plan_service as plans


class WorldPlayerRecord(Base):
    __tablename__ = "world_player_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), nullable=False, index=True)
    source_action_id: Mapped[int] = mapped_column(ForeignKey("world_actions.id"), nullable=False, unique=True)
    object_id: Mapped[str] = mapped_column(String(80), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    visibility: Mapped[str] = mapped_column(String(24), nullable=False, default="private")
    world_day: Mapped[int] = mapped_column(Integer, nullable=False)
    world_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


def save_from_action(db, *, world, action, inputs):
    kind = "private_note" if "private_note" in inputs else "public_note" if "public_note" in inputs else None
    if kind is None:
        return
    from world.atomic_actions import AtomicActionRuntimeError
    text = inputs[kind].strip()
    if action.actor_type != "participant" or not text or len(text) > 500 or kind == "public_note" and inputs.get("publish") is not True:
        raise AtomicActionRuntimeError("Text requires its author and explicit publication permission.", reason_code="permission_denied")
    record = WorldPlayerRecord(session_id=world.session_id, source_action_id=action.id,
        object_id=action.target_object_id, body=text, visibility="private" if kind == "private_note" else "island_public",
        world_day=action.world_day, world_time_minutes=action.world_time_minutes)
    db.add(record)
    db.flush()
    if kind == "public_note":
        from services.phone_plan_service import _new_user_post, _grant_knowledge
        from models import WorldKnowledgeFact
        post = _new_user_post(db, session_id=world.session_id, day=action.world_day,
            time_minutes=action.world_time_minutes, actor_type="participant", actor_agent_id=None,
            content=text, language=action.language, post_type="holiday_note", visibility="island_public",
            commitment_id=None, location_id=action.target_location_id,
            facts={"record_id": record.id, "source_action_id": action.id, "authorship": "participant_self_report"},
            metadata={"allow_comments": False, "self_report_not_verified_fact": True},
            idempotency_key=f"player-record:{action.id}")
        post.source_type, post.source_id = "player_record", record.id
        fact = WorldKnowledgeFact(session_id=world.session_id, fact_key=f"player-record:{record.id}",
            fact_type="participant_self_report", subject_type="participant", subject_id=world.session_id,
            visibility="island_public", source_type="phone_post", source_id=post.id,
            payload_json=plans._json_dumps({"record_id": record.id, "self_report": text, "verified_world_fact": False}),
            world_day=action.world_day, world_time_minutes=action.world_time_minutes)
        db.add(fact)
        db.flush()
        _grant_knowledge(db, fact=fact, actor_key="participant", acquisition_source="authored", source_post_id=post.id,
            day=action.world_day, time_minutes=action.world_time_minutes)
    return record.id


def list_records(db, *, session_id):
    world, spec = plans._world_and_spec(db, session_id)
    rows = db.query(WorldPlayerRecord).filter_by(session_id=session_id).order_by(WorldPlayerRecord.id.desc()).all()
    from models import WorldAction
    import json
    from data.island import localized
    labels = {"move": "前往", "approach": "与居民开始交谈", "conversation_message": "进行对话", "end_conversation": "结束对话", "defined_action": "与物品互动", "atomic_action": "完成活动步骤", "observe": "查看", "end_day": "结束这一天", "wait": "停留休息", "stage_discussion": "参加活动讨论"}
    labels['activity_experience'] = '参加活动'
    history = []
    for action in db.query(WorldAction).filter_by(session_id=session_id, actor_type="participant").filter(WorldAction.action_type.in_(labels)).order_by(WorldAction.id.desc()):
        if action.action_type not in labels:
            continue
        metadata = json.loads(action.metadata_json or "{}")
        if action.action_type == 'activity_experience':
            request = metadata.get('request', {})
            operation = request.get('operation')
            activity = metadata.get('result', {})
            if operation not in ('begin','chat','suggest','game','end'):
                continue
            description = {'begin':'进入活动','chat':'交谈','suggest':'商量接下来的安排','game':'玩桌游','end':'结束活动'}[operation]
            person = spec.residents.get(request.get('speaker_id'))
            text = activity.get('title','活动') + ' · ' + description + (' · '+person.name if person else '')
            history.append({'id':action.id,'world_day':action.world_day,'time_minutes':action.world_time_minutes,'text':text})
            continue
        if action.action_type == "stage_discussion" and metadata.get("status") != "completed":
            continue
        definition_id = metadata.get("action_id", metadata.get("atomic_action", {}).get("action_id"))
        definition = next((a for a in spec.systems.get("action_definitions", ()) if a["action_id"] == definition_id), None)
        place = spec.locations.get(action.target_location_id)
        resident = spec.residents.get(action.target_agent_id)
        text = localized(definition["label"], "zh-CN") if definition else labels[action.action_type]
        if resident:
            text += " · " + resident.name
        if place:
            text += " · " + localized(place.name, "zh-CN")
        history.append({"id": action.id, "world_day": action.world_day, "time_minutes": action.world_time_minutes, "text": text})
    works = json.loads(world.state_json or '{}').get('modular_runtime', {}).get('object_states', {}).get('_v4', {}).get('actors', {}).get('participant', {}).get('works', [])
    return {"history": history, "works": works, "records": [{"id": r.id, "body": r.body, "visibility": r.visibility,
        "world_day": r.world_day, "source_action_id": r.source_action_id,
        "authorship": "participant_self_report"} for r in rows]}
