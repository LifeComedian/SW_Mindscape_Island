from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


EventType = Literal[
    "post_view",
    "like",
    "unlike",
    "skip",
    "comment",
    "agent_reply",
    "user_post",
    "day_advance",
    "finish_session",
]
ActionType = EventType
SessionStatus = Literal["active", "completed", "abandoned"]


class ActivityExperienceRequest(BaseModel):
    participant_ids: list[int] | None = Field(default=None, min_length=1, max_length=3)
    inputs: dict[str, Any] = Field(default_factory=dict)
    actor_agent_id: int | None = Field(default=None, ge=1, le=11)
    operation: Literal['begin', 'chat', 'suggest', 'speech', 'action', 'demonstrate', 'game', 'end']
    idempotency_key: str = Field(min_length=1, max_length=100)
    expected_revision: int | None = Field(default=None, ge=0)
    speaker_id: int | None = Field(default=None, ge=1, le=11)
    message: str = Field(default='', max_length=600)
    choice_id: str = Field(default='', max_length=100)
LanguageCode = Literal["en", "zh-CN"]
WorldActionType = Literal[
    "move",
    "observe",
    "approach",
    "wait",
    "end_day",
    "event_action",
    "seat_view",
    "seat_select",
    "seat_change",
    "scenario_response",
    "scenario_skip",
    "end_conversation",
    "defined_action",
    "read_post",
    "create_post",
    "comment_post",
]


class SessionCreate(BaseModel):
    nickname: str = Field(min_length=1, max_length=80)
    consent: bool
    consent_version: Literal["v0.3"] = "v0.3"
    world_version: str | None = Field(default=None, min_length=1, max_length=128)


class ContentStudioDraft(BaseModel):
    """Unregistered browser draft validated by the runtime content schema."""

    manifest: dict[str, Any]
    map: dict[str, Any]
    locations: dict[str, Any]
    residents: dict[str, Any]
    events: dict[str, Any]
    visuals: dict[str, Any] | None = None
    systems: dict[str, Any] | None = None


class SessionResponse(BaseModel):
    session_id: int
    nickname: str
    user_alias: str
    status: SessionStatus
    current_day: int
    total_days: int
    simulation_seed: int
    world_version: str


class AdvanceDayRequest(BaseModel):
    expected_day: int = Field(ge=1, le=7)


class UserPostCreate(BaseModel):
    content: str = Field(min_length=1, max_length=800)
    language: LanguageCode = "en"
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class InteractionCreate(BaseModel):
    session_id: int
    post_id: int = 0
    agent_id: int | None = None
    action_type: ActionType | None = None
    event_type: EventType | None = None
    content: str = ""
    response_latency_ms: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class InteractionResponse(BaseModel):
    status: str
    interaction_id: int
    event_type: EventType


class AgentReplyRequest(BaseModel):
    idempotency_key: str | None = Field(default=None,min_length=8,max_length=120)
    post_id: int
    agent_id: int
    user_comment: str = Field(min_length=1, max_length=500)
    parent_interaction_id: int | None = None
    parent_community_activity_id: int | None = None
    response_latency_ms: int | None = None
    language: LanguageCode = "en"


class InteractionRecord(BaseModel):
    interaction_id: int
    session_id: int
    event_type: str
    post_id: int
    agent_id: int | None = None
    parent_interaction_id: int | None = None
    parent_community_activity_id: int | None = None
    content: str = ""
    created_at: str
    response_latency_ms: int | None = None
    generation_mode: str | None = None
    model_provider: str | None = None
    model_name: str | None = None
    prompt_version: str | None = None
    safety_flag: bool = False
    world_day: int | None = None
    world_time_minutes: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentReplyResponse(BaseModel):
    comment: InteractionRecord
    agent_reply: InteractionRecord
    generation_metadata: dict[str, Any]


class FinishSessionResponse(BaseModel):
    session_id: int
    status: SessionStatus
    ended_at: str


class ScoreResponse(BaseModel):
    session_id: int
    session_status: str
    prototype_score: float
    prototype_signal_label: str
    prototype_signal_description: str
    score_version: str
    score_breakdown: dict[str, Any]
    has_sufficient_data: bool
    disclaimer: str
    summary: str
    text_features: dict
    behavior_features: dict
    data_quality: dict
    risk_score: float | None = None
    risk_level: str | None = None
    crisis_detected: bool = False


class FeaturesResponse(BaseModel):
    session_id: int
    feature_version: str
    calculated_at: str
    behavior_features: dict
    text_features: dict
    data_quality: dict


class WorldActionRequest(BaseModel):
    action_type: WorldActionType
    idempotency_key: str = Field(min_length=1, max_length=120)
    target_location_id: str | None = Field(default=None, max_length=40)
    target_agent_id: int | None = Field(default=None, ge=1)
    target_object_id: str | None = Field(default=None, max_length=80)
    scenario_instance_id: int | None = Field(default=None, ge=1)
    event_instance_id: int | None = Field(default=None, ge=1)
    event_action_id: str | None = Field(default=None, max_length=80)
    response_text: str = Field(default="", max_length=2000)
    response_latency_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    language: LanguageCode = "en"


class AtomicActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=120)
    expected_revision: int = Field(ge=0)
    target_location_id: str | None = Field(default=None, max_length=40)
    target_actor_type: Literal["participant", "resident"] | None = None
    target_agent_id: int | None = Field(default=None, ge=1)
    target_object_id: str | None = Field(default=None, max_length=128)
    inputs: dict[str, Any] = Field(default_factory=dict)
    language: LanguageCode = "en"


class PlanActorRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_type: Literal["participant", "resident"]
    agent_id: int | None = Field(default=None, ge=1)
    role_id: str | None = Field(default=None, min_length=1, max_length=80)
    required: bool = False


class PlanAvailabilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_day: int = Field(ge=1, le=31)
    start_time_minutes: int = Field(ge=0, le=1439)
    duration_minutes: int = Field(ge=1, le=480)
    location_id: str = Field(min_length=1, max_length=40)
    actors: list[PlanActorRef] = Field(default_factory=list, max_length=20)
    object_ids: list[str] = Field(default_factory=list, max_length=20)
    role_slots: list[str] = Field(default_factory=list, max_length=20)
    exclude_commitment_id: int | None = Field(default=None, ge=1)


class WorldPlanCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipe_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=120)
    location_id: str = Field(min_length=1, max_length=40)
    start_day: int = Field(ge=1, le=31)
    start_time_minutes: int = Field(ge=0, le=1439)
    invitees: list[PlanActorRef] = Field(default_factory=list, max_length=19)
    deadline_day: int | None = Field(default=None, ge=1, le=31)
    deadline_time_minutes: int | None = Field(default=None, ge=0, le=1439)
    reason_code: str = Field(default="plan_proposed", min_length=1, max_length=80)
    language: LanguageCode = "en"


PlanTransitionType = Literal[
    "accept",
    "reject",
    "defer",
    "withdraw",
    "cancel",
    "reschedule",
    "arrive",
    "start",
    "leave",
    "complete",
    "expire",
]


class WorldPlanTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transition: PlanTransitionType
    idempotency_key: str = Field(min_length=1, max_length=120)
    expected_revision: int = Field(ge=0)
    reason_code: str = Field(min_length=1, max_length=80)
    start_day: int | None = Field(default=None, ge=1, le=31)
    start_time_minutes: int | None = Field(default=None, ge=0, le=1439)
    language: LanguageCode = "en"


class PhoneInvitationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipe_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=100)
    audience_scope: Literal["direct", "targeted", "public"]
    invitees: list[PlanActorRef] = Field(default_factory=list, max_length=19)
    location_id: str = Field(min_length=1, max_length=40)
    start_day: int = Field(ge=1, le=31)
    start_time_minutes: int = Field(ge=0, le=1439)
    deadline_day: int | None = Field(default=None, ge=1, le=31)
    deadline_time_minutes: int | None = Field(default=None, ge=0, le=1439)
    organizer_attending: bool = True
    public_headcount: bool = True
    project_to_board: bool = True
    message: str = Field(default="", max_length=500)
    language: LanguageCode = "en"


class PhoneInvitationResponseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response: Literal["accept", "reject", "defer", "withdraw"]
    idempotency_key: str = Field(min_length=1, max_length=100)
    expected_revision: int = Field(ge=0)
    reason_code: str = Field(default="phone_response", min_length=1, max_length=80)
    source_comment_post_id: int | None = Field(default=None, ge=1)


class PhonePostViewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=120)


class PhoneActivityRecordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=100)
    language: LanguageCode = "en"


class PhoneVariantProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_recipe_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=100)
    expected_revision: int = Field(ge=0)
    reason_code: str = Field(default="insufficient_attendance_variant", min_length=1, max_length=80)


class PhoneVariantConsentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["accept", "reject"]
    idempotency_key: str = Field(min_length=1, max_length=100)
    reason_code: str = Field(default="variant_consent", min_length=1, max_length=80)


class EmergenceEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=120)
    source: Literal["manual_test", "foreground_pulse"] = "manual_test"
    source_pulse_id: int | None = Field(default=None, ge=1)
    expected_day: int | None = Field(default=None, ge=1, le=31)
    expected_time_minutes: int | None = Field(default=None, ge=0, le=1439)
    language: LanguageCode = "en"


class EmergentEventTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transition: Literal["reconcile", "technical_failure"]
    idempotency_key: str = Field(min_length=1, max_length=120)


class ResidentDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision_type: Literal["atomic_action", "stage_action", "invitation_response", "reschedule", "event_preference", "dialogue", "invitation_expression", "record_expression"]
    idempotency_key: str = Field(min_length=1, max_length=120)
    language: LanguageCode = "en"
    execution_mode: Literal["execute", "shadow"] = "execute"


class ShadowDecisionCommitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=120)
    language: LanguageCode = "en"


class StageTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["suggest", "confirm", "reject", "execute", "finish", "allow_publication", "revoke_publication", "discuss"]
    idempotency_key: str = Field(min_length=1, max_length=120)
    expected_revision: int = Field(ge=0, strict=True)
    choice_id: str | None = Field(default=None, max_length=128)
    focus_token: str | None = Field(default=None, max_length=128)
    inputs: dict[str, Any] = Field(default_factory=dict)
    language: LanguageCode = "en"


class WorldConversationRequest(BaseModel):
    agent_id: int = Field(ge=1)
    conversation_id: int | None = Field(default=None, ge=1)
    focus_token: str | None = Field(default=None, max_length=128)
    message: str = Field(min_length=1, max_length=1000)
    idempotency_key: str = Field(min_length=1, max_length=120)
    language: LanguageCode = "en"
    response_latency_ms: int | None = Field(default=None, ge=0, le=86_400_000)


class WorldConversationStartRequest(BaseModel):
    agent_id: int = Field(ge=1)
    duration_minutes: Literal[5, 10] = 10
    idempotency_key: str = Field(min_length=1, max_length=120)
    language: LanguageCode = "en"


class InteractionFocusRequest(BaseModel):
    operation: Literal["acquire", "renew", "release", "abandon"]
    runtime_id: int | None = Field(default=None, ge=1)
    conversation_id: int | None = Field(default=None, ge=1)
    focus_token: str | None = Field(default=None, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=120)


class WorldInteractionPromptResponseRequest(BaseModel):
    response: Literal["accept", "later", "decline"]
    idempotency_key: str = Field(min_length=1, max_length=120)
    language: LanguageCode = "en"
    response_latency_ms: int | None = Field(default=None, ge=0, le=86_400_000)


class WorldPulseRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=120)
    expected_revision: int = Field(ge=0)
    source: Literal["foreground_timer", "manual_test"] = "foreground_timer"
    language: LanguageCode = "en"


class WorldSimulationControlRequest(BaseModel):
    mode: Literal["running", "paused"]
    idempotency_key: str = Field(min_length=1, max_length=120)
    expected_revision: int = Field(ge=0)
    language: LanguageCode = "en"
