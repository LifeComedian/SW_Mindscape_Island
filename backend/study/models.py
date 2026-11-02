from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from study.contracts import STUDY_CONTRACT_VERSION, StudyWorkflowState


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class StudySession(Base):
    """Research workflow state kept separate from the legacy game Session."""

    __tablename__ = "study_sessions"
    __table_args__ = (
        CheckConstraint("revision >= 0", name="ck_study_sessions_revision_nonnegative"),
        UniqueConstraint("world_session_id", name="uq_study_sessions_world_session"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    state: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=StudyWorkflowState.CONSENT_PENDING.value,
        index=True,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="zh-CN")
    study_contract_version: Mapped[str] = mapped_column(
        String(80), nullable=False, default=STUDY_CONTRACT_VERSION
    )
    workflow_version: Mapped[str] = mapped_column(
        String(80), nullable=False, default="study-workflow-v1"
    )
    creation_idempotency_key: Mapped[str] = mapped_column(
        String(120), nullable=False, unique=True
    )
    recovery_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    recovery_token_expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    world_session_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("sessions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    compensation_stage: Mapped[str] = mapped_column(
        String(40), nullable=False, default="not_started"
    )
    terminal_reason_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, onupdate=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    transitions: Mapped[list["StudyWorkflowTransition"]] = relationship(
        back_populates="study_session",
        cascade="all, delete-orphan",
        order_by="StudyWorkflowTransition.id",
    )


class StudyConsentRecord(Base):
    __tablename__ = "study_consent_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    study_session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("study_sessions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    consent_version: Mapped[str] = mapped_column(String(80), nullable=False)
    document_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)


class StudyEligibilityDecision(Base):
    """Stores the decision, never the four item-level screening answers."""

    __tablename__ = "study_eligibility_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    study_session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("study_sessions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    criteria_version: Mapped[str] = mapped_column(String(80), nullable=False)
    eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    item_response_count: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    item_responses_deleted_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now
    )
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)


class StudyContactRecord(Base):
    """Restricted identity/contact zone, excluded from game and assessment queries."""

    __tablename__ = "study_contact_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    study_session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("study_sessions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    research_id: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)
    email_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    email_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)


class StudyParticipantProfile(Base):
    """Pseudonymous research data; contains no contact field."""

    __tablename__ = "study_participant_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    study_session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("study_sessions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    research_id: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)
    game_nickname: Mapped[str] = mapped_column(String(40), nullable=False)
    gaming_frequency_code: Mapped[str] = mapped_column(String(40), nullable=False)
    social_game_experience_code: Mapped[str] = mapped_column(String(40), nullable=False)
    ai_text_frequency_code: Mapped[str] = mapped_column(String(40), nullable=False)
    baseline_version: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)


class StudyWorldBoundary(Base):
    """One-to-one bridge and immutable completion boundary for a study world."""

    __tablename__ = "study_world_boundaries"
    __table_args__ = (
        UniqueConstraint("study_session_id", name="uq_study_world_boundary_study"),
        UniqueConstraint("world_session_id", name="uq_study_world_boundary_world"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    study_session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("study_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    world_session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    binding_mode: Mapped[str] = mapped_column(String(40), nullable=False)
    binding_idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    world_version: Mapped[str] = mapped_column(String(40), nullable=False)
    scenario_pack_version: Mapped[str] = mapped_column(String(40), nullable=False)
    observation_schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    feature_schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    bound_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    final_action_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_action_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_world_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_world_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_state_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    integrity_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="open"
    )


class StudyObservationRecord(Base):
    """Content-neutral fact copied from the frozen game boundary."""

    __tablename__ = "study_observation_records"
    __table_args__ = (
        UniqueConstraint(
            "study_session_id",
            "source_type",
            "source_record_id",
            name="uq_study_observation_source",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    study_session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("study_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    world_session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    observation_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_record_id: Mapped[str] = mapped_column(String(80), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    world_day: Mapped[int] = mapped_column(Integer, nullable=False)
    world_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_type: Mapped[str] = mapped_column(String(30), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    observation_type: Mapped[str] = mapped_column(String(60), nullable=False)
    location_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    target_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    opportunity_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    offered_option_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    available_option_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    selected_option_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    outcome_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    technical_status: Mapped[str] = mapped_column(String(40), nullable=False)
    versions_json: Mapped[str] = mapped_column(Text, nullable=False)


class StudyFeatureSnapshot(Base):
    """Fixture-only extraction output. Personality inference is deliberately absent."""

    __tablename__ = "study_feature_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    study_session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("study_sessions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    extractor_version: Mapped[str] = mapped_column(String(80), nullable=False)
    feature_schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    features_json: Mapped[str] = mapped_column(Text, nullable=False)
    opportunity_denominators_json: Mapped[str] = mapped_column(Text, nullable=False)
    missing_reasons_json: Mapped[str] = mapped_column(Text, nullable=False)
    sufficient: Mapped[bool] = mapped_column(Boolean, nullable=False)
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    frozen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)


class StudyAssessmentJob(Base):
    """Version-bound lifecycle for the island-derived estimate.

    M6 permits one primary analysis per study Session. Future administrative
    re-analysis must use a separate versioned record instead of mutating this
    row or its frozen result.
    """

    __tablename__ = "study_assessment_jobs"
    __table_args__ = (
        UniqueConstraint("study_session_id", "analysis_version", name="uq_study_assessment_analysis"),
        CheckConstraint("attempt_count >= 0", name="ck_study_assessment_attempt_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    study_session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("study_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    analysis_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    package_id: Mapped[str] = mapped_column(String(100), nullable=False)
    package_version: Mapped[str] = mapped_column(String(80), nullable=False)
    package_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    input_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    begin_idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, onupdate=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class StudyAssessmentLease(Base):
    """Additive table: a worker may own a job only until this lease expires."""
    __tablename__ = "study_assessment_leases"
    assessment_job_id: Mapped[int] = mapped_column(ForeignKey("study_assessment_jobs.id", ondelete="CASCADE"), primary_key=True)
    token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class StudyAssessmentAttempt(Base):
    """Auditable provider attempt containing encoded features, never raw dialogue."""

    __tablename__ = "study_assessment_attempts"
    __table_args__ = (
        UniqueConstraint("assessment_job_id", "idempotency_key", name="uq_assessment_attempt_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("study_assessment_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    request_schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    request_payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    response_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class StudyGameEstimate(Base):
    """Immutable, schema-validated island estimate or neutral insufficiency record."""

    __tablename__ = "study_game_estimates"
    __table_args__ = (
        UniqueConstraint("study_session_id", "analysis_version", name="uq_study_game_estimate_analysis"),
        UniqueConstraint("assessment_job_id", name="uq_study_game_estimate_job"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    study_session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("study_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assessment_job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("study_assessment_jobs.id", ondelete="RESTRICT"), nullable=False
    )
    analysis_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    result_schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    result_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    fixture_only: Mapped[bool] = mapped_column(Boolean, nullable=False)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    report_text: Mapped[str] = mapped_column(Text, nullable=False)
    output_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    frozen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)


class StudyQuestionnaireDraft(Base):
    """Recoverable partial answers, explicitly distinct from a final submission."""

    __tablename__ = "study_questionnaire_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    study_session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("study_sessions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    instrument_id: Mapped[str] = mapped_column(String(80), nullable=False)
    instrument_version: Mapped[str] = mapped_column(String(120), nullable=False)
    instrument_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    answers_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_payload_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, onupdate=utc_now
    )


class StudyQuestionnaireResponse(Base):
    """Restricted raw-answer partition, frozen after one complete submission."""

    __tablename__ = "study_questionnaire_responses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    study_session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("study_sessions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    instrument_id: Mapped[str] = mapped_column(String(80), nullable=False)
    instrument_version: Mapped[str] = mapped_column(String(120), nullable=False)
    instrument_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    answers_json: Mapped[str] = mapped_column(Text, nullable=False)
    answers_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    submit_idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    frozen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)


class StudyQuestionnaireScore(Base):
    """Deterministic transformed scores and neutral report, separated from raw answers."""

    __tablename__ = "study_questionnaire_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    study_session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("study_sessions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    questionnaire_response_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("study_questionnaire_responses.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    scoring_version: Mapped[str] = mapped_column(String(100), nullable=False)
    transformed_item_scores_json: Mapped[str] = mapped_column(Text, nullable=False)
    domain_scores_json: Mapped[str] = mapped_column(Text, nullable=False)
    facet_scores_json: Mapped[str] = mapped_column(Text, nullable=False)
    report_template_version: Mapped[str] = mapped_column(String(100), nullable=False)
    report_text: Mapped[str] = mapped_column(Text, nullable=False)
    result_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    frozen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)


class StudyFormatExperienceResponse(Base):
    """Frozen Appendix A5 ratings, separate from both assessment results."""

    __tablename__ = "study_format_experience_responses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    study_session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("study_sessions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    instrument_id: Mapped[str] = mapped_column(String(80), nullable=False)
    instrument_version: Mapped[str] = mapped_column(String(120), nullable=False)
    instrument_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    ratings_json: Mapped[str] = mapped_column(Text, nullable=False)
    ratings_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    submit_idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    frozen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)


class StudyResultPresentation(Base):
    """One frozen two-report order bound to the two immutable result hashes."""

    __tablename__ = "study_result_presentations"
    __table_args__ = (
        CheckConstraint(
            "(result_one_kind = 'game_estimate' AND result_two_kind = 'questionnaire') "
            "OR (result_one_kind = 'questionnaire' AND result_two_kind = 'game_estimate')",
            name="ck_study_result_presentations_two_allowed_orders",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    study_session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("study_sessions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    game_estimate_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("study_game_estimates.id", ondelete="RESTRICT"), nullable=False
    )
    questionnaire_score_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("study_questionnaire_scores.id", ondelete="RESTRICT"), nullable=False
    )
    result_one_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    result_two_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    game_output_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    questionnaire_result_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    order_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)


class StudyResultEvaluation(Base):
    """Appendix A6 ratings bound to one report kind and presentation position."""

    __tablename__ = "study_result_evaluations"
    __table_args__ = (
        UniqueConstraint(
            "study_session_id", "report_kind", name="uq_study_result_evaluation_kind"
        ),
        UniqueConstraint(
            "study_session_id", "presentation_position", name="uq_study_result_evaluation_position"
        ),
        CheckConstraint(
            "report_kind IN ('game_estimate', 'questionnaire')",
            name="ck_study_result_evaluation_kind",
        ),
        CheckConstraint(
            "presentation_position IN (1, 2)",
            name="ck_study_result_evaluation_position",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    study_session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("study_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    presentation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("study_result_presentations.id", ondelete="RESTRICT"), nullable=False
    )
    report_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    presentation_position: Mapped[int] = mapped_column(Integer, nullable=False)
    instrument_version: Mapped[str] = mapped_column(String(120), nullable=False)
    instrument_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    first_viewed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    ratings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    ratings_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    submit_idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class StudyComparativeFeedback(Base):
    """Frozen Appendix A7 responses; every optional item has an explicit disposition."""

    __tablename__ = "study_comparative_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    study_session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("study_sessions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    instrument_id: Mapped[str] = mapped_column(String(80), nullable=False)
    instrument_version: Mapped[str] = mapped_column(String(120), nullable=False)
    instrument_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    comparisons_json: Mapped[str] = mapped_column(Text, nullable=False)
    open_feedback_json: Mapped[str] = mapped_column(Text, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    submit_idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    frozen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)


class StudyDebriefAcknowledgement(Base):
    """Version-bound presentation and acknowledgement of Appendix A8."""

    __tablename__ = "study_debrief_acknowledgements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    study_session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("study_sessions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    debrief_version: Mapped[str] = mapped_column(String(120), nullable=False)
    debrief_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    presented_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)
    acknowledge_idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class StudyCompletionReceipt(Base):
    """One receipt per Session. The code is encrypted for replay and separately hashed."""

    __tablename__ = "study_completion_receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    study_session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("study_sessions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    receipt_version: Mapped[str] = mapped_column(String(80), nullable=False)
    completion_code_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    completion_code_sha256: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    display_hint: Mapped[str] = mapped_column(String(8), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)


class StudyCompensationCase(Base):
    """Restricted administrative record. Never joined into research exports."""
    __tablename__ = "study_compensation_cases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    study_session_id: Mapped[int] = mapped_column(ForeignKey("study_sessions.id", ondelete="RESTRICT"), unique=True, nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    amount_fen: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class StudyCompensationAudit(Base):
    __tablename__ = "study_compensation_audits"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("study_compensation_cases.id", ondelete="RESTRICT"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    operator: Mapped[str] = mapped_column(String(80), nullable=False)
    operation: Mapped[str] = mapped_column(String(30), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    before_json: Mapped[str] = mapped_column(Text, nullable=False)
    after_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class StudyWorkflowTransition(Base):
    __tablename__ = "study_workflow_transitions"
    __table_args__ = (
        UniqueConstraint(
            "study_session_id",
            "idempotency_key",
            name="uq_study_transition_session_idempotency",
        ),
        CheckConstraint(
            "result_revision = expected_revision + 1",
            name="ck_study_transition_revision_increment",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    study_session_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("study_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_state: Mapped[str] = mapped_column(String(50), nullable=False)
    to_state: Mapped[str] = mapped_column(String(50), nullable=False)
    expected_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    result_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    related_record_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    related_record_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)

    study_session: Mapped[StudySession] = relationship(back_populates="transitions")


class StudyAvailableResults(Base):
    """V2 freezes report availability and order without fabricating absent scores."""
    __tablename__ = 'study_available_results'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    study_session_id: Mapped[int] = mapped_column(ForeignKey('study_sessions.id', ondelete='CASCADE'), unique=True, nullable=False)
    availability_json: Mapped[str] = mapped_column(Text, nullable=False)
    order_json: Mapped[str] = mapped_column(Text, nullable=False)
    order_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluations_json: Mapped[str] = mapped_column(Text, nullable=False, default='[]')
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now)


class StudyProtocolProgress(Base):
    __tablename__ = 'study_protocol_progress'
    study_session_id: Mapped[int] = mapped_column(ForeignKey('study_sessions.id', ondelete='CASCADE'), primary_key=True)
    baseline_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    questionnaire_skipped_json: Mapped[str] = mapped_column(Text, nullable=False, default='[]')
