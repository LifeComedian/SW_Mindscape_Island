"""Local operator bookkeeping; this module never transfers money."""
import hashlib
import json
import re
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from study.models import StudySession, StudyCompletionReceipt, StudyCompensationCase, StudyCompensationAudit
from study.completion_service import _completion_code_hash, compensation_status
from study.service import StudyWorkflowError, utc_now
from study.access import production_access, StudyInvitation


def _verify_environment(db, study):
    # Reject fixture receipts in production.
    if production_access() and not db.query(StudyInvitation.id).filter_by(
        study_session_id=study.id, purpose="admission", environment="production", status="consumed").first():
        raise StudyWorkflowError("This is not a production admission.", 409, "synthetic_receipt_forbidden")


def lookup_receipt(db, code):
    receipt = db.query(StudyCompletionReceipt).filter_by(completion_code_sha256=_completion_code_hash(code.strip().upper())).one_or_none()
    if receipt is None:
        raise StudyWorkflowError("Completion code is unavailable.", 404, "completion_code_unknown")
    study = db.get(StudySession, receipt.study_session_id)
    _verify_environment(db, study)
    if study.state != "completed":
        raise StudyWorkflowError("The study is not completed.", 409, "completion_state_mismatch")
    case = db.query(StudyCompensationCase).filter_by(study_session_id=study.id).one_or_none()
    return {"study_session_id": study.public_id, "completed_at": str(study.completed_at),
        "eligible_amount_fen": 2000, "case": snapshot(case) if case else None}


def snapshot(case):
    return {"case_id": case.id, "category": case.category, "status": case.status,
        "amount_fen": case.amount_fen, "revision": case.revision}


def open_case(db, *, public_id):
    study = db.query(StudySession).filter_by(public_id=public_id).one_or_none()
    if study is None:
        raise StudyWorkflowError("Session unavailable.", 404, "session_unavailable")
    _verify_environment(db, study)
    existing = db.query(StudyCompensationCase).filter_by(study_session_id=study.id).one_or_none()
    if existing:
        return snapshot(existing)
    category = compensation_status(db, study)["category"]
    if category not in {"full_completion", "started_then_withdrew", "technical_fault"}:
        raise StudyWorkflowError("This case needs no payment record at this stage.", 409, "compensation_not_due")
    if category == "full_completion" and not db.query(StudyCompletionReceipt.id).filter_by(study_session_id=study.id).first():
        raise StudyWorkflowError("Completion receipt missing.", 409, "completion_record_missing")
    case = StudyCompensationCase(study_session_id=study.id, category=category,
        status="pending" if category == "full_completion" else "review_required",
        amount_fen=2000 if category == "full_completion" else None)
    db.add(case)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        case = db.query(StudyCompensationCase).filter_by(study_session_id=study.id).one()
    return snapshot(case)


def update_case(db, *, case_id, operation, expected_revision, operator, idempotency_key, reason_code, amount_fen=None):
    if not operator.strip() or len(operator) > 80 or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", reason_code) or not 1 <= len(idempotency_key) <= 120:
        raise ValueError("Provide a bounded operator, idempotency key and non-identifying reason code.")
    payload = {"case_id": case_id, "operation": operation, "revision": expected_revision, "operator": operator,
        "reason_code": reason_code, "amount_fen": amount_fen}
    sha = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    existing = db.query(StudyCompensationAudit).filter_by(idempotency_key=idempotency_key).one_or_none()
    if existing:
        if existing.request_sha256 != sha:
            raise StudyWorkflowError("The operation key has another payload.", 409, "idempotency_conflict")
        return json.loads(existing.after_json)
    case = db.get(StudyCompensationCase, case_id)
    if case is None:
        raise StudyWorkflowError("Case unavailable.", 404, "compensation_case_unknown")
    study = db.get(StudySession, case.study_session_id)
    # Keep existing payment cases addressable by case ID after erasure.
    if study.workflow_version != 'deleted-admin-stub':
        _verify_environment(db, study)
    before = snapshot(case)
    next_amount = case.amount_fen
    if operation == "approve_manual" and case.status == "review_required":
        if type(amount_fen) is not int or not 0 <= amount_fen <= 2000:
            raise ValueError("Manual review requires an approved amount in fen, between 0 and 2000.")
        if case.category == "full_completion" and amount_fen != 2000:
            raise ValueError("Full completion is fixed at 2000 fen.")
        next_status, next_amount = "pending", amount_fen
    elif operation == "claim" and case.status == "pending":
        next_status = "claimed"
    elif operation == "record_paid" and case.status == "claimed":
        next_status = "paid"
    elif operation == "release_claim" and case.status == "claimed":
        next_status = "pending"
    elif operation == "correct_paid_record" and case.status == "paid":
        next_status = "review_required"  # Administrative correction; never a refund or a second transfer.
    else:
        raise StudyWorkflowError("Invalid compensation transition.", 409, "compensation_transition_invalid")
    changed = db.execute(update(StudyCompensationCase).where(StudyCompensationCase.id == case_id,
        StudyCompensationCase.revision == expected_revision).values(status=next_status, amount_fen=next_amount,
            revision=expected_revision + 1, updated_at=utc_now()))
    if changed.rowcount != 1:
        db.rollback()
        raise StudyWorkflowError("The case changed; reload before acting.", 409, "stale_compensation_revision")
    db.refresh(case)
    after = snapshot(case)
    db.add(StudyCompensationAudit(case_id=case_id, idempotency_key=idempotency_key, request_sha256=sha,
        operator=operator, operation=operation, reason_code=reason_code,
        before_json=json.dumps(before), after_json=json.dumps(after)))
    db.commit()
    return after
