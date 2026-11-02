from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


StudyLanguage = Literal["zh-CN", "en"]


class StudyBootstrapRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: StudyLanguage = "zh-CN"
    idempotency_key: str = Field(min_length=12, max_length=120)
    invitation_code: str | None = Field(default=None, max_length=100)


class StudyBootstrapResponse(BaseModel):
    study_session_id: str
    state: str
    revision: int
    recovery_token: str | None
    recovery_token_issued: bool
    replayed: bool
    current_step_path: str


class StudyCurrentStepResponse(BaseModel):
    study_session_id: str
    state: str
    revision: int
    language: StudyLanguage
    current_step_path: str
    terminal: bool
    can_withdraw: bool
    allowed_actions: list[str]
    study_contract_version: str
    workflow_version: str
    world_session_id: int | None = None


class StudyErrorResponse(BaseModel):
    code: str
    message: str


class StudyCommandBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    idempotency_key: str = Field(min_length=12, max_length=120)


class StudyConsentCommand(StudyCommandBase):
    action: Literal["accept", "decline"]
    consent_version: str = Field(min_length=3, max_length=80)
    document_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


class StudyScreeningCommand(StudyCommandBase):
    age_18_or_older: bool
    located_in_mainland_china: bool
    reads_chinese_and_has_computer: bool
    accepts_ai_interaction_and_recording: bool


class StudyContactCommand(BaseModel):
    idempotency_key: str = Field(min_length=12, max_length=120)
    email: str = Field(min_length=5, max_length=254)


class StudyOnboardingCommand(StudyCommandBase):
    nickname: str = Field(default="", max_length=40)
    gaming_frequency_code: str = Field(min_length=2, max_length=40)
    social_game_experience_code: str = Field(min_length=2, max_length=40)
    ai_text_frequency_code: str = Field(min_length=2, max_length=40)


class StudyWithdrawCommand(StudyCommandBase):
    pass


class StudyWorldCommand(StudyCommandBase):
    pass


class StudyCommandResponse(BaseModel):
    state: str
    revision: int
    current_step_path: str
    replayed: bool = False
    research_id: str | None = None
    world_session_id: int | None = None


class StudyAssessmentStatusResponse(BaseModel):
    state: str
    revision: int
    job_status: str
    attempt_count: int | None = None
    last_error_code: str | None = None
    package_id: str | None = None
    package_version: str | None = None
    package_sha256: str | None = None
    input_sha256: str | None = None
    output_sha256: str | None = None
    fixture_only: bool
    frozen_at: str | None = None


class StudyQuestionnaireItemAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_number: int = Field(ge=1, le=60)
    value: int = Field(ge=1, le=5)


class StudyQuestionnaireDraftCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_draft_revision: int = Field(ge=0)
    idempotency_key: str = Field(min_length=12, max_length=120)
    answers: list[StudyQuestionnaireItemAnswer] = Field(max_length=60)
    skipped_items: list[int] = Field(default_factory=list, max_length=60)


class StudyQuestionnaireSubmitCommand(StudyCommandBase):
    answers: list[StudyQuestionnaireItemAnswer] = Field(max_length=60)
    skipped_items: list[int] = Field(default_factory=list, max_length=60)


class StudyFormatExperienceRating(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format_id: Literal["island", "questionnaire"]
    item_number: int = Field(ge=1, le=6, strict=True)
    value: int | None = Field(default=None, ge=1, le=7, strict=True)
    skipped: bool


class StudyFormatExperienceSubmitCommand(StudyCommandBase):
    ratings: list[StudyFormatExperienceRating] = Field(min_length=12, max_length=12)


class StudyResultRating(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_number: int = Field(ge=1, le=4, strict=True)
    value: int | None = Field(default=None, ge=1, le=7, strict=True)
    skipped: bool


class StudyResultEvaluationSubmitCommand(StudyCommandBase):
    ratings: list[StudyResultRating] = Field(min_length=4, max_length=4)


class StudyComparativeChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_number: int = Field(ge=1, le=10, strict=True)
    choice: Literal["island", "questionnaire", "about_same", "unsure", "skipped", "not_applicable"]


class StudyOpenFeedbackAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_number: int = Field(ge=1, le=6, strict=True)
    value: str | None = Field(default=None, max_length=2000)
    skipped: bool


class StudyComparativeFeedbackSubmitCommand(StudyCommandBase):
    comparisons: list[StudyComparativeChoice] = Field(min_length=10, max_length=10)
    open_feedback: list[StudyOpenFeedbackAnswer] = Field(min_length=6, max_length=6)
