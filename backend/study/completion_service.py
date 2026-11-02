from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import hashlib
import json
import secrets
import string
import threading
from typing import Any, Iterable

from sqlalchemy.orm import Session as DBSession

from study.completion_instruments import (
    COMPARATIVE_INSTRUMENT_ID,
    COMPARATIVE_INSTRUMENT_SHA256,
    COMPARATIVE_INSTRUMENT_VERSION,
    DEBRIEF_SHA256,
    DEBRIEF_VERSION,
    comparative_instrument_payload,
    debrief_payload,
)
from study.contracts import StudyWorkflowState
from study.models import (
    StudyComparativeFeedback,
    StudyCompletionReceipt,
    StudyContactRecord,
    StudyDebriefAcknowledgement,
    StudySession,
    StudyWorkflowTransition,
)
from study.participant_service import decrypt_restricted_value, encrypt_restricted_value
from study.service import StudyWorkflowError, transition_study_session, utc_now


COMPLETION_RECEIPT_VERSION = "study-completion-receipt-v1"
_COMPARATIVE_CHOICES = frozenset(
    {"island", "questionnaire", "about_same", "unsure", "skipped", "not_applicable"}
)
_COMPLETION_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_COMPLETION_LOCKS: dict[int, threading.Lock] = {}
_COMPLETION_LOCKS_GUARD = threading.Lock()


@dataclass(frozen=True, slots=True)
class CompletionFlowResponse:
    study_session: StudySession
    replayed: bool


def _lock(study_session_id: int) -> threading.Lock:
    with _COMPLETION_LOCKS_GUARD:
        return _COMPLETION_LOCKS.setdefault(study_session_id, threading.Lock())


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _normalize_comparisons(rows: Iterable[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in rows:
        item_number = int(row.item_number)
        choice = str(row.choice)
        if item_number in seen:
            raise StudyWorkflowError(
                "Each comparison item may appear only once.",
                422,
                "comparative_feedback_duplicate_item",
            )
        if choice not in _COMPARATIVE_CHOICES:
            raise StudyWorkflowError(
                "Unknown comparison choice.", 422, "comparative_feedback_invalid_choice"
            )
        seen.add(item_number)
        normalized.append({"item_number": item_number, "choice": choice})
    if seen != set(range(1, 11)):
        raise StudyWorkflowError(
            "All ten comparison items must be answered or explicitly skipped.",
            422,
            "comparative_feedback_incomplete",
        )
    return sorted(normalized, key=lambda item: item["item_number"])


def _normalize_open_feedback(rows: Iterable[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in rows:
        item_number = int(row.item_number)
        skipped = bool(row.skipped)
        raw_value = row.value
        value = raw_value.strip() if isinstance(raw_value, str) else None
        if item_number in seen:
            raise StudyWorkflowError(
                "Each open-feedback item may appear only once.",
                422,
                "open_feedback_duplicate_item",
            )
        if skipped == bool(value):
            raise StudyWorkflowError(
                "Each open-feedback item must contain text or be explicitly skipped, but not both.",
                422,
                "open_feedback_disposition_invalid",
            )
        if value is not None and len(value) > 2000:
            raise StudyWorkflowError(
                "Open feedback is too long.", 422, "open_feedback_too_long"
            )
        seen.add(item_number)
        normalized.append(
            {"item_number": item_number, "value": value, "skipped": skipped}
        )
    if seen != set(range(1, 7)):
        raise StudyWorkflowError(
            "All six open-feedback items must contain text or be explicitly skipped.",
            422,
            "open_feedback_incomplete",
        )
    return sorted(normalized, key=lambda item: item["item_number"])


def begin_comparison(
    db: DBSession,
    *,
    study_session: StudySession,
    expected_revision: int,
    idempotency_key: str,
) -> CompletionFlowResponse:
    with _lock(study_session.id):
        db.rollback()
        study_session = db.query(StudySession).filter_by(id=study_session.id).one()
        if study_session.state == StudyWorkflowState.COMPARATIVE_FEEDBACK.value:
            return CompletionFlowResponse(study_session, True)
        if study_session.state != StudyWorkflowState.RESULT_TWO_RATED.value:
            raise StudyWorkflowError(
                "Comparative feedback is unavailable at this stage.",
                409,
                "comparative_feedback_not_available",
            )
        result = transition_study_session(
            db,
            study_session_id=study_session.id,
            requested_state=StudyWorkflowState.COMPARATIVE_FEEDBACK,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            source="participant",
            reason_code="comparative_feedback_started",
            related_record_type="instrument",
            related_record_id=COMPARATIVE_INSTRUMENT_VERSION,
        )
        return CompletionFlowResponse(result.study_session, result.replayed)


def comparison_payload(study_session: StudySession, db=None) -> dict[str, object]:
    if study_session.state != StudyWorkflowState.COMPARATIVE_FEEDBACK.value:
        raise StudyWorkflowError(
            "Comparative feedback content is available only during its active stage.",
            409,
            "comparative_feedback_not_active",
        )
    from study.protocol_v2 import enabled, comparison_instrument
    if enabled(study_session):
        from study.available_results import not_applicable_items
        return {**comparison_instrument(), "not_applicable_items":not_applicable_items(db,study_session)}
    return comparative_instrument_payload()


def submit_comparison(
    db: DBSession,
    *,
    study_session: StudySession,
    comparison_rows: Iterable[Any],
    open_feedback_rows: Iterable[Any],
    expected_revision: int,
    idempotency_key: str,
) -> CompletionFlowResponse:
    from study.protocol_v2 import enabled, comparison_instrument, debrief_instrument
    instrument = comparison_instrument() if enabled(study_session) else {"instrument_id":COMPARATIVE_INSTRUMENT_ID,"instrument_version":COMPARATIVE_INSTRUMENT_VERSION,"instrument_sha256":COMPARATIVE_INSTRUMENT_SHA256}
    debrief = debrief_instrument() if enabled(study_session) else debrief_payload()
    comparisons = _normalize_comparisons(comparison_rows)
    from study.available_results import not_applicable_items
    na=set(not_applicable_items(db,study_session)) if enabled(study_session) else set()
    if any((r["choice"]=="not_applicable") != (r["item_number"] in na) for r in comparisons):
        raise StudyWorkflowError("Report comparison availability mismatch.",422,"comparison_applicability_invalid")
    open_feedback = _normalize_open_feedback(open_feedback_rows)
    payload_sha256 = _sha(
        {
            "instrument_sha256": instrument["instrument_sha256"],
            "comparisons": comparisons,
            "open_feedback": open_feedback,
        }
    )
    with _lock(study_session.id):
        db.rollback()
        study_session = db.query(StudySession).filter_by(id=study_session.id).one()
        existing = (
            db.query(StudyComparativeFeedback)
            .filter_by(study_session_id=study_session.id)
            .one_or_none()
        )
        if existing is not None:
            if existing.payload_sha256 != payload_sha256:
                raise StudyWorkflowError(
                    "Comparative feedback is frozen and cannot be changed.",
                    409,
                    "comparative_feedback_frozen",
                )
            return CompletionFlowResponse(study_session, True)
        if study_session.state != StudyWorkflowState.COMPARATIVE_FEEDBACK.value:
            raise StudyWorkflowError(
                "Comparative feedback is not active.",
                409,
                "comparative_feedback_not_active",
            )
        if study_session.revision != expected_revision:
            raise StudyWorkflowError("Study workflow revision is stale.", 409, "stale_revision")

        now = utc_now()
        response = StudyComparativeFeedback(
            study_session_id=study_session.id,
            instrument_id=instrument["instrument_id"],
            instrument_version=instrument["instrument_version"],
            instrument_sha256=instrument["instrument_sha256"],
            language="zh-CN",
            comparisons_json=_canonical(comparisons),
            open_feedback_json=_canonical(open_feedback),
            payload_sha256=payload_sha256,
            submit_idempotency_key=idempotency_key,
            submitted_at=now,
            frozen_at=now,
        )
        acknowledgement = StudyDebriefAcknowledgement(
            study_session_id=study_session.id,
            debrief_version=debrief["debrief_version"],
            debrief_sha256=debrief["debrief_sha256"],
            language="zh-CN",
            presented_at=now,
        )
        db.add_all((response, acknowledgement))
        db.flush()
        result = transition_study_session(
            db,
            study_session_id=study_session.id,
            requested_state=StudyWorkflowState.DEBRIEF,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            source="participant",
            reason_code="comparative_feedback_frozen",
            related_record_type="comparative_feedback",
            related_record_id=str(response.id),
        )
        return CompletionFlowResponse(result.study_session, result.replayed)


def get_debrief(db: DBSession, study_session: StudySession) -> dict[str, object]:
    if study_session.state != StudyWorkflowState.DEBRIEF.value:
        raise StudyWorkflowError(
            "Debriefing is available only after comparative feedback.",
            409,
            "debrief_not_active",
        )
    acknowledgement = (
        db.query(StudyDebriefAcknowledgement)
        .filter_by(study_session_id=study_session.id)
        .one_or_none()
    )
    if acknowledgement is None:
        raise StudyWorkflowError("Debrief record is missing.", 500, "debrief_record_missing")
    from study.protocol_v2 import enabled, debrief_instrument
    debrief = debrief_instrument(acknowledgement.debrief_version) if enabled(study_session) else debrief_payload()
    if (
        acknowledgement.debrief_version != debrief["debrief_version"]
        or acknowledgement.debrief_sha256 != debrief["debrief_sha256"]
    ):
        raise StudyWorkflowError("Debrief version is inconsistent.", 500, "debrief_version_error")
    return debrief


def _new_completion_code() -> str:
    groups = [
        "".join(secrets.choice(_COMPLETION_ALPHABET) for _ in range(4))
        for _group in range(3)
    ]
    return f"MSI-{'-'.join(groups)}"


def _completion_code_hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _create_receipt(db: DBSession, study_session_id: int) -> StudyCompletionReceipt:
    for _attempt in range(5):
        code = _new_completion_code()
        digest = _completion_code_hash(code)
        if db.query(StudyCompletionReceipt).filter_by(completion_code_sha256=digest).first():
            continue
        receipt = StudyCompletionReceipt(
            study_session_id=study_session_id,
            receipt_version=COMPLETION_RECEIPT_VERSION,
            completion_code_ciphertext=encrypt_restricted_value(code),
            completion_code_sha256=digest,
            display_hint=code[-4:],
            generated_at=utc_now(),
        )
        db.add(receipt)
        db.flush()
        return receipt
    raise StudyWorkflowError(
        "Could not allocate a completion code.", 503, "completion_code_unavailable"
    )


def acknowledge_debrief(
    db: DBSession,
    *,
    study_session: StudySession,
    expected_revision: int,
    idempotency_key: str,
) -> CompletionFlowResponse:
    with _lock(study_session.id):
        db.rollback()
        study_session = db.query(StudySession).filter_by(id=study_session.id).one()
        acknowledgement = (
            db.query(StudyDebriefAcknowledgement)
            .filter_by(study_session_id=study_session.id)
            .one_or_none()
        )
        receipt = (
            db.query(StudyCompletionReceipt)
            .filter_by(study_session_id=study_session.id)
            .one_or_none()
        )
        if study_session.state == StudyWorkflowState.COMPLETED.value:
            if acknowledgement is None or acknowledgement.acknowledged_at is None or receipt is None:
                raise StudyWorkflowError(
                    "Completion records are incomplete.", 500, "completion_record_missing"
                )
            return CompletionFlowResponse(study_session, True)
        if study_session.state != StudyWorkflowState.DEBRIEF.value:
            raise StudyWorkflowError(
                "Debrief acknowledgement is unavailable at this stage.",
                409,
                "debrief_not_active",
            )
        if acknowledgement is None:
            raise StudyWorkflowError("Debrief record is missing.", 500, "debrief_record_missing")
        if study_session.revision != expected_revision:
            raise StudyWorkflowError("Study workflow revision is stale.", 409, "stale_revision")
        if receipt is None:
            receipt = _create_receipt(db, study_session.id)
        acknowledgement.acknowledge_idempotency_key = idempotency_key
        acknowledgement.acknowledged_at = utc_now()
        study_session.compensation_stage = "study_completed"
        db.flush()
        result = transition_study_session(
            db,
            study_session_id=study_session.id,
            requested_state=StudyWorkflowState.COMPLETED,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            source="participant",
            reason_code="debrief_acknowledged",
            related_record_type="completion_receipt",
            related_record_id=str(receipt.id),
        )
        return CompletionFlowResponse(result.study_session, result.replayed)


def _iso_utc(value) -> str:
    return value.isoformat(timespec="seconds") + "Z"


def completion_payload(db: DBSession, study_session: StudySession) -> dict[str, object]:
    if study_session.state != StudyWorkflowState.COMPLETED.value:
        raise StudyWorkflowError(
            "Completion receipt is available only after study completion.",
            409,
            "completion_not_available",
        )
    receipt = (
        db.query(StudyCompletionReceipt)
        .filter_by(study_session_id=study_session.id)
        .one_or_none()
    )
    contact = (
        db.query(StudyContactRecord)
        .filter_by(study_session_id=study_session.id)
        .one_or_none()
    )
    if receipt is None or contact is None or study_session.completed_at is None:
        raise StudyWorkflowError(
            "Completion receipt is incomplete.", 500, "completion_record_missing"
        )
    code = decrypt_restricted_value(receipt.completion_code_ciphertext)
    if not secrets.compare_digest(_completion_code_hash(code), receipt.completion_code_sha256):
        raise StudyWorkflowError(
            "Completion receipt integrity check failed.", 500, "completion_integrity_error"
        )
    return {
        "status": "completed",
        "title": "研究流程已完成",
        "message": "感谢您完成本次研究流程。请妥善保存下面的研究编号和完成码。",
        "completed_at": _iso_utc(study_session.completed_at),
        "research_id": contact.research_id,
        "completion_code": code,
        "reward_amount_yuan": 20,
        "claim_by": None if __import__("study.protocol_v2",fromlist=["enabled"]).enabled(study_session) else _iso_utc(study_session.completed_at + timedelta(days=7)),
        "contact_email": "researcher@example.invalid",
        "contact_wechat": "[RESEARCHER_WECHAT]",
        "claim_note": "请私下提供完成码，研究者在收到必要核验信息后7个自然日内微信转账20元。跳题或报告不可用不影响完整参加的补偿资格。无需提交答案、对话或报告截图。" if __import__("study.protocol_v2",fromlist=["enabled"]).enabled(study_session) else "请在完成后一周内联系研究者并提供完成码，核验后领取 20 元。验证码只能领取一次；如有技术问题或错过联系时间，请联系研究者核查。系统不会自动扣除或取消您依知情同意材料应得的补偿。",
        "screenshot_note": (
            "您可以自行截取或保存本页作为完成记录；这不是获得补偿的强制条件。"
            "本系统不接收或保存截图。补偿安排以已获批准的知情同意材料和研究团队通知为准。"
        ),
        "screenshot_required": False,
        "screenshot_uploaded": False,
    }


def compensation_status(db: DBSession, study_session: StudySession) -> dict[str, object]:
    transitions = (
        db.query(StudyWorkflowTransition.to_state)
        .filter_by(study_session_id=study_session.id)
        .all()
    )
    activity_started = any(
        to_state
        in {
            StudyWorkflowState.ISLAND_ACTIVE.value,
            StudyWorkflowState.ISLAND_DEPARTURE_PENDING.value,
            StudyWorkflowState.ISLAND_COMPLETED.value,
        }
        for (to_state,) in transitions
    )
    from study.protocol_v2 import enabled
    from study.models import StudyProtocolProgress
    if enabled(study_session):
        started=db.get(StudyProtocolProgress,study_session.id)
        activity_started=bool(started and started.baseline_started_at)
    state = StudyWorkflowState(study_session.state)
    if state is StudyWorkflowState.COMPLETED:
        category = "full_completion"
    elif state is StudyWorkflowState.TECHNICAL_INCOMPLETE:
        category = "technical_fault" if activity_started or not enabled(study_session) else "before_start_exit"
    elif state is StudyWorkflowState.WITHDRAWN:
        category = "started_then_withdrew" if activity_started else "before_start_withdrawal"
    elif state in {
        StudyWorkflowState.CONSENT_DECLINED,
        StudyWorkflowState.ELIGIBILITY_INELIGIBLE,
    }:
        category = "before_start_exit"
    else:
        category = "in_progress"
    return {
        "category": category,
        "workflow_state": state.value,
        "activity_started": activity_started,
        "recorded_stage": study_session.compensation_stage,
        "payment_executed": False,
        "calculation_only": True,
    }
