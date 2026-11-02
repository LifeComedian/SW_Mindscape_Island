from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
import uuid

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from study.contracts import (
    STUDY_CONTRACT_VERSION,
    TERMINAL_STATES,
    StudyContractError,
    StudyWorkflowState,
    assert_transition_allowed,
)
from study.models import StudySession, StudyWorkflowTransition


WORKFLOW_VERSION = "study-workflow-v1"
DEFAULT_RECOVERY_TTL = timedelta(hours=24)


class StudyWorkflowError(RuntimeError):
    def __init__(self, message: str, status_code: int = 409, code: str = "study_conflict"):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    study_session: StudySession
    recovery_token: str | None
    replayed: bool


@dataclass(frozen=True, slots=True)
class TransitionResult:
    study_session: StudySession
    transition: StudyWorkflowTransition
    replayed: bool


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def hash_recovery_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def bootstrap_study_session(
    db: DBSession,
    *,
    language: str,
    idempotency_key: str,
    recovery_ttl: timedelta = DEFAULT_RECOVERY_TTL,
) -> BootstrapResult:
    existing = (
        db.query(StudySession)
        .filter(StudySession.creation_idempotency_key == idempotency_key)
        .one_or_none()
    )
    if existing is not None:
        if existing.language != language:
            raise StudyWorkflowError(
                "Idempotency key was already used with different bootstrap data.",
                409,
                "idempotency_collision",
            )
        return BootstrapResult(existing, None, True)

    if language not in {"zh-CN", "en"}:
        raise StudyWorkflowError("Unsupported study language.", 422, "invalid_language")
    if recovery_ttl <= timedelta(0):
        raise StudyWorkflowError("Recovery lifetime must be positive.", 500, "invalid_config")

    recovery_token = secrets.token_urlsafe(32)
    now = utc_now()
    study_session = StudySession(
        public_id=f"study_{uuid.uuid4().hex}",
        state=StudyWorkflowState.CONSENT_PENDING.value,
        revision=0,
        language=language,
        study_contract_version=STUDY_CONTRACT_VERSION,
        workflow_version=__import__("study.protocol_v2",fromlist=["configured_workflow"]).configured_workflow(),
        creation_idempotency_key=idempotency_key,
        recovery_token_hash=hash_recovery_token(recovery_token),
        recovery_token_expires_at=now + recovery_ttl,
        created_at=now,
        updated_at=now,
    )
    db.add(study_session)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(StudySession)
            .filter(StudySession.creation_idempotency_key == idempotency_key)
            .one_or_none()
        )
        if existing is not None:
            if existing.language != language:
                raise StudyWorkflowError(
                    "Idempotency key was already used with different bootstrap data.",
                    409,
                    "idempotency_collision",
                )
            return BootstrapResult(existing, None, True)
        raise
    db.refresh(study_session)
    return BootstrapResult(study_session, recovery_token, False)


def get_study_session(db: DBSession, public_id: str) -> StudySession:
    study_session = (
        db.query(StudySession).filter(StudySession.public_id == public_id).one_or_none()
    )
    if study_session is None:
        raise StudyWorkflowError("Study session not found.", 404, "study_not_found")
    return study_session


def authenticate_study_session(
    db: DBSession,
    *,
    public_id: str,
    recovery_token: str,
    now: datetime | None = None,
) -> StudySession:
    from study.research_admin import revoked
    if revoked(public_id):
        raise StudyWorkflowError('Study session not found.',404,'study_not_found')
    study_session = get_study_session(db, public_id)
    supplied_hash = hash_recovery_token(recovery_token)
    if not hmac.compare_digest(study_session.recovery_token_hash, supplied_hash):
        raise StudyWorkflowError("Study session not found.", 404, "study_not_found")
    if study_session.recovery_token_expires_at <= (now or utc_now()):
        raise StudyWorkflowError(
            "Study recovery credential has expired.",
            401,
            "recovery_expired",
        )
    return study_session


def transition_study_session(
    db: DBSession,
    *,
    study_session_id: int,
    requested_state: StudyWorkflowState,
    expected_revision: int,
    idempotency_key: str,
    source: str,
    reason_code: str,
    related_record_type: str | None = None,
    related_record_id: str | None = None,
) -> TransitionResult:
    replay = (
        db.query(StudyWorkflowTransition)
        .filter(
            StudyWorkflowTransition.study_session_id == study_session_id,
            StudyWorkflowTransition.idempotency_key == idempotency_key,
        )
        .one_or_none()
    )
    if replay is not None:
        if (
            replay.to_state != requested_state.value
            or replay.expected_revision != expected_revision
            or replay.source != source
            or replay.reason_code != reason_code
            or replay.related_record_type != related_record_type
            or replay.related_record_id != related_record_id
        ):
            raise StudyWorkflowError(
                "Idempotency key was already used with a different transition.",
                409,
                "idempotency_collision",
            )
        study_session = db.query(StudySession).filter(StudySession.id == study_session_id).one()
        return TransitionResult(study_session, replay, True)

    study_session = db.query(StudySession).filter(StudySession.id == study_session_id).one_or_none()
    if study_session is None:
        raise StudyWorkflowError("Study session not found.", 404, "study_not_found")
    if study_session.revision != expected_revision:
        raise StudyWorkflowError(
            "Study workflow revision is stale.",
            409,
            "stale_revision",
        )
    try:
        current_state = StudyWorkflowState(study_session.state)
        from study.holiday_flow import applies
        revised_results = (current_state == StudyWorkflowState.QUESTIONNAIRE_COMPLETED and requested_state == StudyWorkflowState.RESULTS_READY
                           and source == 'system' and reason_code == 'holiday_v3_no_pre_result_feedback' and applies(db,study_session))
        from study.protocol_v2 import allows_transition
        if not revised_results and not allows_transition(study_session,current_state,requested_state,source,reason_code):
            assert_transition_allowed(current_state, requested_state)
    except (ValueError, StudyContractError) as exc:
        raise StudyWorkflowError(str(exc), 409, "invalid_transition") from exc
    now = utc_now()
    terminal_reason = reason_code if requested_state in TERMINAL_STATES else None
    completed_at = now if requested_state is StudyWorkflowState.COMPLETED else None
    result_revision = expected_revision + 1
    result = db.execute(
        update(StudySession)
        .where(
            StudySession.id == study_session_id,
            StudySession.state == current_state.value,
            StudySession.revision == expected_revision,
        )
        .values(
            state=requested_state.value,
            revision=result_revision,
            updated_at=now,
            terminal_reason_code=terminal_reason,
            completed_at=completed_at,
        )
    )
    if result.rowcount != 1:
        db.rollback()
        replay = (
            db.query(StudyWorkflowTransition)
            .filter(
                StudyWorkflowTransition.study_session_id == study_session_id,
                StudyWorkflowTransition.idempotency_key == idempotency_key,
            )
            .one_or_none()
        )
        if (
            replay is not None
            and replay.to_state == requested_state.value
            and replay.expected_revision == expected_revision
            and replay.source == source
            and replay.reason_code == reason_code
            and replay.related_record_type == related_record_type
            and replay.related_record_id == related_record_id
        ):
            refreshed = db.query(StudySession).filter(StudySession.id == study_session_id).one()
            return TransitionResult(refreshed, replay, True)
        raise StudyWorkflowError(
            "Study workflow changed concurrently.",
            409,
            "stale_revision",
        )

    transition = StudyWorkflowTransition(
        study_session_id=study_session_id,
        from_state=current_state.value,
        to_state=requested_state.value,
        expected_revision=expected_revision,
        result_revision=result_revision,
        idempotency_key=idempotency_key,
        source=source,
        reason_code=reason_code,
        related_record_type=related_record_type,
        related_record_id=related_record_id,
        created_at=now,
    )
    db.add(transition)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        replay = (
            db.query(StudyWorkflowTransition)
            .filter(
                StudyWorkflowTransition.study_session_id == study_session_id,
                StudyWorkflowTransition.idempotency_key == idempotency_key,
            )
            .one_or_none()
        )
        if (
            replay is None
            or replay.to_state != requested_state.value
            or replay.expected_revision != expected_revision
            or replay.source != source
            or replay.reason_code != reason_code
            or replay.related_record_type != related_record_type
            or replay.related_record_id != related_record_id
        ):
            raise StudyWorkflowError(
                "Study transition conflicted with another request.",
                409,
                "transition_conflict",
            ) from exc
        refreshed = db.query(StudySession).filter(StudySession.id == study_session_id).one()
        return TransitionResult(refreshed, replay, True)

    refreshed = db.query(StudySession).filter(StudySession.id == study_session_id).one()
    db.refresh(transition)
    return TransitionResult(refreshed, transition, False)
