from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from typing import Any

from sqlalchemy.orm import Session as DBSession

from models import Session as WorldSession, WorldAction, WorldState
from services.interaction_prompt_service import invalidate_pending_interaction_prompts
from services.simulation_service import initialize_simulation
from services.world_service import (
    WorldStateError,
    ensure_session_can_finish,
    initialize_world,
    session_write_lock,
)
from study.assessment_interfaces import (
    FEATURE_SCHEMA_VERSION,
    FixtureCountFeatureExtractor,
)
from study.contracts import OBSERVATION_SCHEMA_VERSION, ObservationEvent, StudyWorkflowState
from study.models import (
    StudyConsentRecord,
    StudyFeatureSnapshot,
    StudyObservationRecord,
    StudyParticipantProfile,
    StudySession,
    StudyWorkflowTransition,
    StudyWorldBoundary,
)
from study.service import StudyWorkflowError, transition_study_session, utc_now
from world.registry import get_world_spec


@dataclass(frozen=True, slots=True)
class WorldBridgeResult:
    study_session: StudySession
    boundary: StudyWorldBoundary
    replayed: bool


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _fixture_world_version() -> str:
    runtime = os.getenv("STUDY_RUNTIME_ENV", "").lower()
    enabled = os.getenv("STUDY_TEST_FIXTURES_ENABLED", "").lower() == "true"
    if runtime not in {"test", "development"} or not enabled:
        raise StudyWorkflowError(
            "The authored study world is not available yet.",
            409,
            "study_world_unavailable",
        )
    version = os.getenv("STUDY_TEST_WORLD_VERSION", "study-m6-fixture-v1")
    if version == "island-v0.7":
        raise StudyWorkflowError(
            "The blank authoring template cannot be bound as a playable study world.",
            409,
            "authoring_template_not_playable",
        )
    try:
        get_world_spec(version)
    except KeyError as exc:
        raise StudyWorkflowError(
            "The configured fixture world is unavailable.",
            409,
            "study_world_unavailable",
        ) from exc
    return version


def _authored_world_version():
    from types import SimpleNamespace
    from study.production_letter import package
    if os.getenv('STUDY_ASSESSMENT_MODE') != 'observation' or os.getenv('STUDY_WORLD_VERSION') != 'chaoxi-holiday-v6':
        raise StudyWorkflowError('Configure the authored V6 observation world.',409,'study_world_unavailable')
    try: spec=get_world_spec('chaoxi-holiday-v6')
    except KeyError as exc: raise StudyWorkflowError('Install the V6 content pack.',409,'study_world_unavailable') from exc
    if spec.experience.get('fixture_only'):
        raise StudyWorkflowError('Fixture content is forbidden.',409,'study_world_unavailable')
    package(SimpleNamespace(world_version=spec.world_version,scenario_pack_version=spec.scenario_pack_version,feature_schema_version='holiday-observation-features-v1'))
    return spec.world_version


def configured_world_available(session):
    from study.protocol_v2 import enabled
    try:
        _authored_world_version() if enabled(session) else _fixture_world_version()
        return True
    except StudyWorkflowError:
        return False


def _boundary_for(db: DBSession, study_session_id: int) -> StudyWorldBoundary | None:
    return (
        db.query(StudyWorldBoundary)
        .filter(StudyWorldBoundary.study_session_id == study_session_id)
        .one_or_none()
    )


def bind_fixture_world(
    db: DBSession,
    *,
    study_session: StudySession,
    expected_revision: int,
    idempotency_key: str,
) -> WorldBridgeResult:
    existing = _boundary_for(db, study_session.id)
    if existing is not None:
        if existing.binding_idempotency_key != idempotency_key:
            raise StudyWorkflowError(
                "This study session is already bound to a world.", 409, "world_already_bound"
            )
        return WorldBridgeResult(study_session, existing, True)
    if study_session.state != StudyWorkflowState.ONBOARDING.value:
        raise StudyWorkflowError(
            "The study session is not ready to enter the island.", 409, "invalid_transition"
        )
    profile = (
        db.query(StudyParticipantProfile)
        .filter_by(study_session_id=study_session.id)
        .one_or_none()
    )
    consent = (
        db.query(StudyConsentRecord)
        .filter_by(study_session_id=study_session.id)
        .one_or_none()
    )
    if profile is None or consent is None:
        raise StudyWorkflowError(
            "Onboarding records are incomplete.", 409, "onboarding_incomplete"
        )
    from study.protocol_v2 import enabled
    world_version = _authored_world_version() if enabled(study_session) else _fixture_world_version()
    now = utc_now()
    world_session = WorldSession(
        nickname=profile.game_nickname,
        user_alias=profile.game_nickname,
        consent=True,
        consent_version=consent.consent_version,
        status="active",
        created_at=now,
        started_at=now,
        current_day=1,
        total_days=7,
    )
    db.add(world_session)
    db.flush()
    initialize_simulation(db, world_session, commit=False)
    world = initialize_world(
        db,
        world_session,
        world_version=world_version,
        commit=False,
    )
    from study.holiday_assessment_v5 import local_feature_schema
    boundary = StudyWorldBoundary(
        study_session_id=study_session.id,
        world_session_id=world_session.id,
        binding_mode="authored_observation" if enabled(study_session) else "isolated_fixture",
        binding_idempotency_key=idempotency_key,
        world_version=world.world_version,
        scenario_pack_version=world.scenario_pack_version,
        observation_schema_version=OBSERVATION_SCHEMA_VERSION,
        feature_schema_version='holiday-observation-features-v1' if world_version=='chaoxi-holiday-v6' else local_feature_schema() if world_version in ('chaoxi-holiday-v5', 'chaoxi-holiday-v6') else FEATURE_SCHEMA_VERSION,
        bound_at=now,
        integrity_status="open",
    )
    db.add(boundary)
    study_session.world_session_id = world_session.id
    result = transition_study_session(
        db,
        study_session_id=study_session.id,
        requested_state=StudyWorkflowState.ISLAND_ACTIVE,
        expected_revision=expected_revision,
        idempotency_key=idempotency_key,
        source="participant",
        reason_code="authored_world_bound" if enabled(study_session) else "fixture_world_bound",
        related_record_type="world_session",
        related_record_id=str(world_session.id),
    )
    db.refresh(boundary)
    return WorldBridgeResult(result.study_session, boundary, result.replayed)


def request_departure(
    db: DBSession,
    *,
    study_session: StudySession,
    expected_revision: int,
    idempotency_key: str,
) -> WorldBridgeResult:
    boundary = _boundary_for(db, study_session.id)
    if boundary is None or study_session.world_session_id is None:
        raise StudyWorkflowError("No world is bound.", 409, "world_not_bound")
    world_session = db.query(WorldSession).filter_by(id=boundary.world_session_id).one()
    try:
        ensure_session_can_finish(db, world_session)
    except WorldStateError as exc:
        raise StudyWorkflowError(str(exc), exc.status_code, "departure_too_early") from exc
    result = transition_study_session(
        db,
        study_session_id=study_session.id,
        requested_state=StudyWorkflowState.ISLAND_DEPARTURE_PENDING,
        expected_revision=expected_revision,
        idempotency_key=idempotency_key,
        source="participant",
        reason_code="departure_requested",
        related_record_type="world_session",
        related_record_id=str(boundary.world_session_id),
    )
    return WorldBridgeResult(result.study_session, boundary, result.replayed)


def cancel_departure(
    db: DBSession,
    *,
    study_session: StudySession,
    expected_revision: int,
    idempotency_key: str,
) -> WorldBridgeResult:
    boundary = _boundary_for(db, study_session.id)
    if boundary is None:
        raise StudyWorkflowError("No world is bound.", 409, "world_not_bound")
    result = transition_study_session(
        db,
        study_session_id=study_session.id,
        requested_state=StudyWorkflowState.ISLAND_ACTIVE,
        expected_revision=expected_revision,
        idempotency_key=idempotency_key,
        source="participant",
        reason_code="departure_cancelled",
        related_record_type="world_session",
        related_record_id=str(boundary.world_session_id),
    )
    return WorldBridgeResult(result.study_session, boundary, result.replayed)


def _string_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(dict.fromkeys(item for item in value if isinstance(item, str) and item))


def _observation_for(
    action: WorldAction,
    *,
    study_session: StudySession,
    boundary: StudyWorldBoundary,
) -> ObservationEvent:
    try:
        metadata = json.loads(action.metadata_json or "{}")
    except (TypeError, ValueError):
        metadata = {}
    offered = _string_list(metadata.get("offered_option_ids"))
    available_raw = _string_list(metadata.get("available_option_ids"))
    available = tuple(item for item in (available_raw or offered) if item in offered)
    selected_raw = metadata.get("selected_option_id")
    selected = selected_raw if isinstance(selected_raw, str) and selected_raw in available else None
    target_type: str | None = None
    target_id: str | None = None
    if action.target_agent_id is not None:
        target_type, target_id = "agent", str(action.target_agent_id)
    elif action.target_object_id:
        target_type, target_id = "object", action.target_object_id
    elif action.target_location_id:
        target_type, target_id = "location", action.target_location_id
    versions = {
        "world_version": boundary.world_version,
        "scenario_pack_version": boundary.scenario_pack_version,
        "observation_schema_version": boundary.observation_schema_version,
        "policy_version": action.policy_version or "not_recorded",
    }
    return ObservationEvent(
        observation_id=f"study-{study_session.id}-world-action-{action.id}",
        study_session_id=study_session.public_id,
        world_session_id=boundary.world_session_id,
        occurred_at=action.created_at.isoformat(),
        world_day=action.world_day,
        world_time_minutes=action.world_time_minutes,
        actor_type=action.actor_type,
        actor_id=str(action.actor_agent_id) if action.actor_agent_id is not None else None,
        observation_type=action.action_type,
        source="world_action",
        location_id=action.target_location_id or metadata.get("location_id"),
        target_type=target_type,
        target_id=target_id,
        opportunity_id=metadata.get("opportunity_id") if isinstance(metadata.get("opportunity_id"), str) else None,
        offered_option_ids=offered,
        available_option_ids=available,
        selected_option_id=selected,
        outcome_code=(
            metadata.get("outcome_code")
            if isinstance(metadata.get("outcome_code"), str)
            else action.decision_reason_code or "recorded"
        ),
        technical_status="complete",
        versions=versions,
    )


def _persist_observation(
    db: DBSession,
    event: ObservationEvent,
    *,
    study_session_id: int,
    source_record_id: str,
) -> StudyObservationRecord:
    occurred_at = datetime.fromisoformat(event.occurred_at)
    row = StudyObservationRecord(
        study_session_id=study_session_id,
        world_session_id=event.world_session_id,
        observation_id=event.observation_id,
        schema_version=event.schema_version,
        source_type=event.source,
        source_record_id=source_record_id,
        occurred_at=occurred_at,
        world_day=event.world_day,
        world_time_minutes=event.world_time_minutes,
        actor_type=event.actor_type,
        actor_id=event.actor_id,
        observation_type=event.observation_type,
        location_id=event.location_id,
        target_type=event.target_type,
        target_id=event.target_id,
        opportunity_id=event.opportunity_id,
        offered_option_ids_json=_json(list(event.offered_option_ids)),
        available_option_ids_json=_json(list(event.available_option_ids)),
        selected_option_id=event.selected_option_id,
        outcome_code=event.outcome_code,
        technical_status=event.technical_status,
        versions_json=_json(dict(event.versions)),
    )
    db.add(row)
    return row


def confirm_departure(
    db: DBSession,
    *,
    study_session: StudySession,
    expected_revision: int,
    idempotency_key: str,
) -> WorldBridgeResult:
    boundary = _boundary_for(db, study_session.id)
    if boundary is None:
        raise StudyWorkflowError("No world is bound.", 409, "world_not_bound")
    replay = (
        db.query(StudyWorkflowTransition)
        .filter_by(study_session_id=study_session.id, idempotency_key=idempotency_key)
        .one_or_none()
    )
    if replay is not None:
        if (
            replay.to_state != StudyWorkflowState.ISLAND_COMPLETED.value
            or replay.expected_revision != expected_revision
        ):
            raise StudyWorkflowError(
                "Idempotency key was already used with a different transition.",
                409,
                "idempotency_collision",
            )
        return WorldBridgeResult(study_session, boundary, True)
    if boundary.frozen_at is not None:
        raise StudyWorkflowError("The world is already frozen.", 409, "world_frozen")

    with session_write_lock(boundary.world_session_id):
        db.rollback()
        study_session = db.query(StudySession).filter_by(id=study_session.id).one()
        boundary = _boundary_for(db, study_session.id)
        assert boundary is not None
        world_session = db.query(WorldSession).filter_by(id=boundary.world_session_id).one()
        world = db.query(WorldState).filter_by(session_id=boundary.world_session_id).one()
        try:
            ensure_session_can_finish(db, world_session)
        except WorldStateError as exc:
            raise StudyWorkflowError(str(exc), exc.status_code, "departure_too_early") from exc
        actions = (
            db.query(WorldAction)
            .filter_by(session_id=boundary.world_session_id)
            .order_by(WorldAction.id)
            .all()
        )
        observations = [
            _observation_for(action, study_session=study_session, boundary=boundary)
            for action in actions
        ]
        for action, observation in zip(actions, observations, strict=True):
            _persist_observation(
                db,
                observation,
                study_session_id=study_session.id,
                source_record_id=str(action.id),
            )
        if boundary.world_version in ('chaoxi-holiday-v5', 'chaoxi-holiday-v6'):
            from study.holiday_assessment_v5 import extract
            extracted = extract(db, boundary.world_session_id, observations,
                                feature_schema=boundary.feature_schema_version)
        else:
            extracted = FixtureCountFeatureExtractor().extract(observations)
        frozen_features = dict(extracted.features)
        if boundary.world_version == 'chaoxi-holiday-v6' and __import__('os').getenv('STUDY_ASSESSMENT_MODE') == 'observation':
            from study.controlled_report_service import read_session_records
            from study.controlled_report import extract_facts
            from study.production_letter import FACT_KEY
            records = read_session_records(db, boundary.world_session_id)
            frozen_features[FACT_KEY] = extract_facts(records, boundary.world_session_id)
            from content.experience_next import enabled
            if enabled():
                from study.island_recap import build_recap
                frozen_features[FACT_KEY]['recap'] = build_recap(records)
        frozen_at = utc_now()
        db.add(
            StudyFeatureSnapshot(
                study_session_id=study_session.id,
                extractor_version=extracted.extractor_version,
                feature_schema_version=extracted.feature_schema_version,
                features_json=_json(frozen_features),
                opportunity_denominators_json=_json(dict(extracted.opportunity_denominators)),
                missing_reasons_json=_json(dict(extracted.missing_reasons)),
                sufficient=extracted.sufficient,
                observation_count=extracted.observation_count,
                frozen_at=frozen_at,
            )
        )
        last_action_id = actions[-1].id if actions else None
        integrity_payload = {
            "world_session_id": boundary.world_session_id,
            "world_version": boundary.world_version,
            "scenario_pack_version": boundary.scenario_pack_version,
            "day": world.current_day,
            "time_minutes": world.current_time_minutes,
            "participant_location_id": world.participant_location_id,
            "state_json": json.loads(world.state_json or "{}"),
            "final_action_id": last_action_id,
            "final_action_count": len(actions),
        }
        boundary.frozen_at = frozen_at
        boundary.final_action_id = last_action_id
        boundary.final_action_count = len(actions)
        boundary.final_world_day = world.current_day
        boundary.final_world_time_minutes = world.current_time_minutes
        boundary.final_state_sha256 = hashlib.sha256(
            _json(integrity_payload).encode("utf-8")
        ).hexdigest()
        boundary.integrity_status = "frozen"
        world_session.status = "completed"
        world_session.ended_at = frozen_at
        invalidate_pending_interaction_prompts(
            db, world=world, reason_code="study_world_frozen"
        )
        result = transition_study_session(
            db,
            study_session_id=study_session.id,
            requested_state=StudyWorkflowState.ISLAND_COMPLETED,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            source="participant",
            reason_code="departure_confirmed_world_frozen",
            related_record_type="study_world_boundary",
            related_record_id=str(boundary.id),
        )
        db.refresh(boundary)
    return WorldBridgeResult(result.study_session, boundary, result.replayed)
