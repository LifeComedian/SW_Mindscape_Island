from __future__ import annotations

import hashlib
import os
import re
import secrets

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from study.contracts import StudyWorkflowState
from study.models import (
    StudyConsentRecord,
    StudyContactRecord,
    StudyEligibilityDecision,
    StudyParticipantProfile,
    StudySession,
)
from study.service import StudyWorkflowError


CONSENT_VERSION = "1.0-2026-09-27"
CONSENT_DOCUMENT_SHA256 = "3ce474fe749cb7154f3646b8fad006b52bcf28198cf2ab150973aa149228b112"
ELIGIBILITY_CRITERIA_VERSION = "appendix-a1-2026-09-27"
BASELINE_VERSION = "appendix-a2-2026-09-27"

GAMING_FREQUENCY_CODES = {
    "never", "lt_monthly", "monthly_1_3", "weekly_1_4", "weekly_5_plus"
}
SOCIAL_GAME_EXPERIENCE_CODES = {
    "never", "lt_5h", "5_20h", "gt_20h", "unsure"
}
AI_TEXT_FREQUENCY_CODES = {
    "never", "once_twice", "occasional", "monthly", "weekly_plus"
}

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_DIRECT_IDENTIFIER_RE = re.compile(
    r"(?:@|\b\d{6,}\b|\b1[3-9]\d{9}\b|(?:电话|手机|邮箱|学号|身份证|地址))",
    re.IGNORECASE,
)


def _contact_fernet() -> Fernet:
    configured = os.getenv("STUDY_CONTACT_ENCRYPTION_KEY", "").strip()
    if not configured:
        raise StudyWorkflowError(
            "Contact encryption is not configured.", 503, "contact_encryption_unavailable"
        )
    try:
        return Fernet(configured.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise StudyWorkflowError(
            "Contact encryption is misconfigured.", 503, "contact_encryption_unavailable"
        ) from exc


def create_test_contact_key() -> str:
    return Fernet.generate_key().decode("ascii")


def encrypt_restricted_value(value: str) -> str:
    return _contact_fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_restricted_value(ciphertext: str) -> str:
    try:
        return _contact_fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise StudyWorkflowError(
            "Restricted data cannot be decrypted.", 500, "restricted_data_decryption_failed"
        ) from exc


def encrypt_contact_email(email: str) -> str:
    return encrypt_restricted_value(email)


def decrypt_contact_email(ciphertext: str) -> str:
    try:
        return decrypt_restricted_value(ciphertext)
    except StudyWorkflowError as exc:
        raise StudyWorkflowError(
            "Contact data cannot be decrypted.", 500, "contact_decryption_failed"
        ) from exc


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 254 or not _EMAIL_RE.fullmatch(email):
        raise StudyWorkflowError("Please provide a valid email address.", 422, "invalid_email")
    return email


def validate_nickname(value: str) -> str:
    nickname = " ".join(value.strip().split())
    if not 1 <= len(nickname) <= 20:
        raise StudyWorkflowError("Nickname must contain 1 to 20 characters.", 422, "invalid_nickname")
    if _DIRECT_IDENTIFIER_RE.search(nickname):
        raise StudyWorkflowError(
            "Nickname appears to contain identifying information.", 422, "nickname_may_identify"
        )
    return nickname


def generate_research_id() -> str:
    return f"MSI-{secrets.token_hex(4).upper()}"


def email_digest(email: str) -> str:
    return hashlib.sha256(email.encode("utf-8")).hexdigest()


def record_contact(
    db: DBSession, *, study_session: StudySession, email: str
) -> tuple[StudyContactRecord, bool]:
    existing = db.query(StudyContactRecord).filter_by(study_session_id=study_session.id).one_or_none()
    normalized = normalize_email(email)
    digest = email_digest(normalized)
    if existing:
        if existing.email_sha256 != digest:
            raise StudyWorkflowError("Contact was already submitted.", 409, "contact_collision")
        return existing, True
    if study_session.state != StudyWorkflowState.ELIGIBILITY_CONFIRMED.value:
        raise StudyWorkflowError("Contact cannot be submitted at this step.", 409, "invalid_transition")

    for _attempt in range(4):
        row = StudyContactRecord(
            study_session_id=study_session.id,
            research_id=generate_research_id(),
            email_ciphertext=encrypt_contact_email(normalized),
            email_sha256=digest,
        )
        db.add(row)
        try:
            db.commit()
            db.refresh(row)
            return row, False
        except IntegrityError:
            db.rollback()
    raise StudyWorkflowError("Could not allocate a research ID.", 503, "research_id_unavailable")


def record_profile(
    db: DBSession,
    *,
    study_session: StudySession,
    nickname: str,
    gaming_frequency_code: str,
    social_game_experience_code: str,
    ai_text_frequency_code: str,
) -> StudyParticipantProfile:
    from study.protocol_v2 import enabled
    revised=enabled(study_session)
    if revised and not nickname.strip(): nickname="旅人"+study_session.public_id[-6:]
    existing = db.query(StudyParticipantProfile).filter_by(study_session_id=study_session.id).one_or_none()
    if existing:
        proposed = (
            validate_nickname(nickname),
            gaming_frequency_code,
            social_game_experience_code,
            ai_text_frequency_code,
        )
        recorded = (
            existing.game_nickname,
            existing.gaming_frequency_code,
            existing.social_game_experience_code,
            existing.ai_text_frequency_code,
        )
        if proposed != recorded:
            raise StudyWorkflowError(
                "Onboarding was already submitted with different values.",
                409,
                "idempotency_collision",
            )
        return existing
    contact = db.query(StudyContactRecord).filter_by(study_session_id=study_session.id).one_or_none()
    if contact is None:
        raise StudyWorkflowError("Contact arrangement is required first.", 409, "contact_required")
    if gaming_frequency_code not in GAMING_FREQUENCY_CODES | ({"skipped"} if revised else set()):
        raise StudyWorkflowError("Unknown gaming frequency option.", 422, "invalid_baseline_option")
    if social_game_experience_code not in SOCIAL_GAME_EXPERIENCE_CODES | ({"skipped"} if revised else set()):
        raise StudyWorkflowError("Unknown social-game experience option.", 422, "invalid_baseline_option")
    if ai_text_frequency_code not in AI_TEXT_FREQUENCY_CODES | ({"skipped"} if revised else set()):
        raise StudyWorkflowError("Unknown AI interaction option.", 422, "invalid_baseline_option")
    profile = StudyParticipantProfile(
        study_session_id=study_session.id,
        research_id=contact.research_id,
        game_nickname=validate_nickname(nickname),
        gaming_frequency_code=gaming_frequency_code,
        social_game_experience_code=social_game_experience_code,
        ai_text_frequency_code=ai_text_frequency_code,
        baseline_version="appendix-a2-20261018-v2" if revised else BASELINE_VERSION,
    )
    db.add(profile)
    db.flush()
    return profile
