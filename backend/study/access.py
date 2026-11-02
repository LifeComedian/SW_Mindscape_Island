"""Single-use invitations and recovery credentials."""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import os
import secrets
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, String, update
from sqlalchemy.orm import Mapped, Session, mapped_column

from database import Base
from study.models import StudySession
from study.service import BootstrapResult, StudyWorkflowError, hash_recovery_token, utc_now
from study.contracts import STUDY_CONTRACT_VERSION, StudyWorkflowState
from study.service import WORKFLOW_VERSION


class StudyInvitation(Base):
    __tablename__ = "study_invitations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    batch: Mapped[str] = mapped_column(String(80), nullable=False)
    environment: Mapped[str] = mapped_column(String(20), nullable=False)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False, default="admission")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="issued")
    study_session_id: Mapped[int | None] = mapped_column(ForeignKey("study_sessions.id"), nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class StudyAccessAudit(Base):
    __tablename__ = "study_access_audits"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invitation_id: Mapped[int] = mapped_column(ForeignKey("study_invitations.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    operator: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)


def production_access() -> bool:
    return os.getenv("STUDY_RUNTIME_ENV", "").lower() == "production"


def invitation_required() -> bool:
    return production_access() or os.getenv("STUDY_INVITATION_REQUIRED", "").lower() == "true"


def access_environment() -> str:
    return "production" if production_access() else "synthetic"


def invitation_hash(code: str) -> str:
    return hashlib.sha256(code.strip().encode("utf-8")).hexdigest()


def issue_invitation(db: Session, *, batch: str, operator: str, ttl: timedelta,
                     recovery_session: StudySession | None = None) -> tuple[StudyInvitation, str]:
    if not 0 < ttl.total_seconds() <= 90 * 86400 or not 1 <= len(batch.strip()) <= 80 or not 1 <= len(operator.strip()) <= 80:
        raise ValueError("Specify operator, batch and a lifetime of at most 90 days.")
    if recovery_session:
        for previous in db.query(StudyInvitation).filter_by(study_session_id=recovery_session.id, purpose="recovery", status="issued").all():
            previous.status = "revoked"
            db.add(StudyAccessAudit(invitation_id=previous.id, action="superseded_recovery", operator=operator))
    code = "SW-" + secrets.token_urlsafe(24)
    row = StudyInvitation(code_hash=invitation_hash(code), batch=batch,
                          environment=access_environment(), purpose="recovery" if recovery_session else "admission",
                          study_session_id=recovery_session.id if recovery_session else None,
                          expires_at=utc_now() + ttl)
    db.add(row)
    db.flush()
    db.add(StudyAccessAudit(invitation_id=row.id, action="issue_" + row.purpose, operator=operator))
    db.commit()
    return row, code  # Raw credential returned once; never stored or logged.


def revoke_invitation(db: Session, invitation_id: int, *, operator: str) -> None:
    if not 1 <= len(operator.strip()) <= 80:
        raise ValueError("Specify a bounded operator identity.")
    result = db.execute(update(StudyInvitation).where(StudyInvitation.id == invitation_id,
                        StudyInvitation.status == "issued").values(status="revoked"))
    if result.rowcount != 1:
        db.rollback()
        raise StudyWorkflowError("Credential is unavailable.", 409, "credential_unavailable")
    db.add(StudyAccessAudit(invitation_id=invitation_id, action="revoke", operator=operator))
    db.commit()


def redeem_invitation(db: Session, *, code: str, language: str) -> BootstrapResult:
    """Claim and bootstrap/rotate in one transaction; a race has only one winner."""
    now = utc_now()
    row = db.query(StudyInvitation).filter_by(code_hash=invitation_hash(code)).one_or_none()
    if row is None or row.environment != access_environment():
        raise StudyWorkflowError("邀请码无效、已使用或已过期，请联系研究者。", 403, "invitation_unavailable")
    claimed = db.execute(update(StudyInvitation).where(StudyInvitation.id == row.id,
                         StudyInvitation.status == "issued", StudyInvitation.expires_at > now)
                         .values(status="consumed", consumed_at=now))
    if claimed.rowcount != 1:
        db.rollback()
        raise StudyWorkflowError("邀请码无效、已使用或已过期，请联系研究者。", 403, "invitation_unavailable")
    token = secrets.token_urlsafe(32)
    if row.purpose == "recovery":
        session = db.get(StudySession, row.study_session_id)
        if session is None:
            db.rollback()
            raise StudyWorkflowError("Credential is unavailable.", 403, "invitation_unavailable")
        # The previous browser loses access immediately, including an unexpired token.
        session.recovery_token_hash = hash_recovery_token(token)
        session.recovery_token_expires_at = now + timedelta(days=14)
    else:
        session = StudySession(public_id=f"study_{uuid.uuid4().hex}",
            state=StudyWorkflowState.CONSENT_PENDING.value, revision=0, language=language,
            study_contract_version=STUDY_CONTRACT_VERSION, workflow_version=__import__("study.protocol_v2",fromlist=["configured_workflow"]).configured_workflow(),
            creation_idempotency_key=f"invitation_{row.id}",
            recovery_token_hash=hash_recovery_token(token), recovery_token_expires_at=now + timedelta(days=14))
        db.add(session)
        db.flush()
        row.study_session_id = session.id
    db.commit()
    return BootstrapResult(session, token, False)
