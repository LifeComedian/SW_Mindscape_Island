from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def utc_now() -> datetime:
    return datetime.utcnow()


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nickname: Mapped[str] = mapped_column(String(80), nullable=False)
    user_alias: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    consent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    consent_version: Mapped[str] = mapped_column(String(40), nullable=False, default="v0.3")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    current_day: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    total_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    simulation_seed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    virtual_start_date: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)

    interactions: Mapped[list["Interaction"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )
    community_activities: Mapped[list["CommunityActivity"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )
    notifications: Mapped[list["Notification"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )
    simulation_events: Mapped[list["SimulationEvent"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )
    agent_memories: Mapped[list["AgentMemory"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )
    user_posts: Mapped[list["UserPost"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )
    world_state: Mapped["WorldState | None"] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        uselist=False,
    )
    character_states: Mapped[list["CharacterState"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )
    world_actions: Mapped[list["WorldAction"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )
    world_memories: Mapped[list["WorldMemory"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )
    scenario_instances: Mapped[list["ScenarioInstance"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )
    world_conversations: Mapped[list["WorldConversation"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )
    world_conversation_participants: Mapped[list["WorldConversationParticipant"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )
    relationships: Mapped[list["RelationshipState"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )
    relationship_changes: Mapped[list["RelationshipChange"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )
    world_event_instances: Mapped[list["WorldEventInstance"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )
    world_scheduled_events: Mapped[list["WorldScheduledEvent"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )
    world_event_trigger_evaluations: Mapped[list["WorldEventTriggerEvaluation"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )
    world_simulation_pulses: Mapped[list["WorldSimulationPulse"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )
    resident_intent_states: Mapped[list["ResidentIntentState"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )
    world_interaction_prompts: Mapped[list["WorldInteractionPrompt"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )


class Interaction(Base):
    __tablename__ = "interactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sessions.id"),
        index=True,
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    post_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    agent_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    parent_interaction_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("interactions.id"),
        nullable=True,
    )
    parent_community_activity_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("community_activities.id"),
        nullable=True,
    )
    action_type: Mapped[str] = mapped_column(String(30), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    response_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generation_mode: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model_provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    safety_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    world_day: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    world_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    session: Mapped[Session] = relationship(back_populates="interactions")
    parent: Mapped["Interaction | None"] = relationship(
        remote_side=[id],
        backref="agent_replies",
    )
    parent_community_activity: Mapped["CommunityActivity | None"] = relationship(
        foreign_keys=[parent_community_activity_id],
    )


class UserPost(Base):
    __tablename__ = "user_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    feed_post_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        unique=True,
        index=True,
    )
    session_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sessions.id"),
        nullable=False,
        index=True,
    )
    day: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    author_alias: Mapped[str] = mapped_column(String(80), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    simulated_time: Mapped[str] = mapped_column(String(5), nullable=False)
    world_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    author_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="participant", index=True
    )
    author_agent_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    post_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="personal", index=True
    )
    visibility: Mapped[str] = mapped_column(
        String(30), nullable=False, default="island_public", index=True
    )
    source_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    location_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    facts_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    session: Mapped[Session] = relationship(back_populates="user_posts")


class CommunityActivity(Base):
    __tablename__ = "community_activities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sessions.id"),
        nullable=False,
        index=True,
    )
    day: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    post_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    actor_agent_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    target_agent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parent_activity_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("community_activities.id"),
        nullable=True,
    )
    activity_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    content_en: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_zh_cn: Mapped[str] = mapped_column(Text, nullable=False, default="")
    response_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generation_mode: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model_provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    safety_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    world_day: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    world_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    simulated_time: Mapped[str] = mapped_column(String(5), nullable=False, default="12:00")
    blueprint_key: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    session: Mapped[Session] = relationship(back_populates="community_activities")
    parent: Mapped["CommunityActivity | None"] = relationship(
        remote_side=[id],
        backref="replies",
    )

    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "blueprint_key",
            name="uq_community_activity_session_blueprint",
        ),
    )


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sessions.id"),
        nullable=False,
        index=True,
    )
    day: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    agent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    post_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notification_type: Mapped[str] = mapped_column(String(30), nullable=False)
    content_en: Mapped[str] = mapped_column(Text, nullable=False)
    content_zh_cn: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    world_day: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    world_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    session: Mapped[Session] = relationship(back_populates="notifications")


class SimulationEvent(Base):
    __tablename__ = "simulation_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sessions.id"),
        nullable=False,
        index=True,
    )
    event_key: Mapped[str] = mapped_column(String(80), nullable=False)
    source_post_id: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome_post_id: Mapped[int] = mapped_column(Integer, nullable=False)
    resolved_day: Mapped[int] = mapped_column(Integer, nullable=False)
    branch: Mapped[str] = mapped_column(String(30), nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    session: Mapped[Session] = relationship(back_populates="simulation_events")

    __table_args__ = (
        UniqueConstraint("session_id", "event_key", name="uq_simulation_event_session_key"),
    )


class AgentMemory(Base):
    __tablename__ = "agent_memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sessions.id"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    comment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    like_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skip_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_post_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_user_comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    session: Mapped[Session] = relationship(back_populates="agent_memories")

    __table_args__ = (
        UniqueConstraint("session_id", "agent_id", name="uq_agent_memory_session_agent"),
    )


class WorldState(Base):
    __tablename__ = "world_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sessions.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    current_day: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    current_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=540)
    participant_location_id: Mapped[str] = mapped_column(
        String(40), nullable=False, default="harbor", index=True
    )
    world_version: Mapped[str] = mapped_column(
        String(40), nullable=False, default="island-v0.3"
    )
    scenario_pack_version: Mapped[str] = mapped_column(
        String(40), nullable=False, default="island-scenarios-v0.3"
    )
    state_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    session: Mapped[Session] = relationship(back_populates="world_state")


class CharacterState(Base):
    __tablename__ = "character_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id"), nullable=False, index=True
    )
    agent_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    current_location_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    current_activity: Mapped[str] = mapped_column(String(120), nullable=False)
    current_goal: Mapped[str] = mapped_column(String(240), nullable=False)
    schedule_state: Mapped[str] = mapped_column(String(80), nullable=False)
    state_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    session: Mapped[Session] = relationship(back_populates="character_states")

    __table_args__ = (
        UniqueConstraint("session_id", "agent_id", name="uq_character_state_session_agent"),
    )


class WorldSimulationPulse(Base):
    __tablename__ = "world_simulation_pulses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    source: Mapped[str] = mapped_column(
        String(40), nullable=False, default="foreground_timer"
    )
    requested_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    before_day: Mapped[int] = mapped_column(Integer, nullable=False)
    before_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    after_day: Mapped[int] = mapped_column(Integer, nullable=False)
    after_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    action_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    result_snapshot_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}"
    )
    policy_id: Mapped[str] = mapped_column(
        String(80), nullable=False, default="foreground-pulse"
    )
    policy_version: Mapped[str] = mapped_column(
        String(40), nullable=False, default="v1"
    )
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    session: Mapped[Session] = relationship(back_populates="world_simulation_pulses")

    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "idempotency_key",
            name="uq_world_simulation_pulse_session_key",
        ),
        UniqueConstraint(
            "session_id",
            "sequence",
            name="uq_world_simulation_pulse_session_sequence",
        ),
    )


class ResidentIntentState(Base):
    __tablename__ = "resident_intent_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id"), nullable=False, index=True
    )
    agent_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    intent_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="active", index=True
    )
    target_location_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    target_actor_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    target_agent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_object_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    started_day: Mapped[int] = mapped_column(Integer, nullable=False)
    started_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    due_day: Mapped[int] = mapped_column(Integer, nullable=False)
    due_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    source_pulse_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("world_simulation_pulses.id"), nullable=True, index=True
    )
    source_action_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("world_actions.id"), nullable=True, index=True
    )
    policy_id: Mapped[str] = mapped_column(String(80), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    summary_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    session: Mapped[Session] = relationship(back_populates="resident_intent_states")

    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "agent_id",
            name="uq_resident_intent_state_session_agent",
        ),
    )


class WorldAction(Base):
    __tablename__ = "world_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id"), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    actor_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="participant", index=True
    )
    actor_agent_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    policy_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    policy_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decision_reason_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    action_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    target_location_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    target_agent_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    target_object_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    scenario_instance_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("scenario_instances.id"), nullable=True, index=True
    )
    event_instance_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("world_event_instances.id"), nullable=True, index=True
    )
    response_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    response_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    world_day: Mapped[int] = mapped_column(Integer, nullable=False)
    world_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)

    session: Mapped[Session] = relationship(back_populates="world_actions")

    __table_args__ = (
        UniqueConstraint(
            "session_id", "idempotency_key", name="uq_world_action_session_idempotency"
        ),
    )


class WorldAtomicActionExecution(Base):
    """One idempotent M7 atomic-action attempt and its authoritative outcome."""

    __tablename__ = "world_atomic_action_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id"), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    actor_agent_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    action_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    affordance_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    target_location_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    target_actor_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    target_agent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_object_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    requested_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    source_action_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("world_actions.id"), nullable=True, index=True
    )
    inputs_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    effects_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    result_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    runtime_version: Mapped[str] = mapped_column(String(80), nullable=False)
    contract_version: Mapped[str] = mapped_column(String(80), nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "idempotency_key",
            name="uq_world_atomic_action_session_key",
        ),
    )


class WorldEventInstance(Base):
    __tablename__ = "world_event_instances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    event_version: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="active", index=True
    )
    location_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    state_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    trigger_key: Mapped[str] = mapped_column(String(120), nullable=False)
    started_day: Mapped[int] = mapped_column(Integer, nullable=False)
    started_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome_code: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    session: Mapped[Session] = relationship(back_populates="world_event_instances")

    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "trigger_key",
            name="uq_world_event_instance_session_trigger",
        ),
    )


class WorldScheduledEvent(Base):
    __tablename__ = "world_scheduled_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id"), nullable=False, index=True
    )
    parent_event_instance_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("world_event_instances.id"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    event_version: Mapped[str] = mapped_column(String(40), nullable=False)
    due_day: Mapped[int] = mapped_column(Integer, nullable=False)
    due_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    deduplication_key: Mapped[str] = mapped_column(String(120), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="scheduled", index=True
    )
    delivered_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivered_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_event_instance_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("world_event_instances.id"), nullable=True, index=True
    )
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    session: Mapped[Session] = relationship(back_populates="world_scheduled_events")
    parent_event: Mapped[WorldEventInstance | None] = relationship(
        foreign_keys=[parent_event_instance_id]
    )
    result_event: Mapped[WorldEventInstance | None] = relationship(
        foreign_keys=[result_event_instance_id]
    )

    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "deduplication_key",
            name="uq_world_scheduled_event_session_dedup",
        ),
    )


class WorldEventTriggerEvaluation(Base):
    __tablename__ = "world_event_trigger_evaluations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id"), nullable=False, index=True
    )
    source_action_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("world_actions.id"), nullable=False, index=True
    )
    selected_event_instance_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("world_event_instances.id"), nullable=True, index=True
    )
    trigger_key: Mapped[str] = mapped_column(String(120), nullable=False)
    event_pack_version: Mapped[str] = mapped_column(String(40), nullable=False)
    trigger_counter: Mapped[int] = mapped_column(Integer, nullable=False)
    world_day: Mapped[int] = mapped_column(Integer, nullable=False)
    world_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    location_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    candidate_event_ids_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )
    selected_event_id: Mapped[str | None] = mapped_column(
        String(80), nullable=True, index=True
    )
    outcome: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    deterministic_roll: Mapped[float | None] = mapped_column(Float, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    session: Mapped[Session] = relationship(
        back_populates="world_event_trigger_evaluations"
    )
    selected_event: Mapped[WorldEventInstance | None] = relationship(
        foreign_keys=[selected_event_instance_id]
    )

    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "trigger_key",
            name="uq_world_event_trigger_evaluation_session_key",
        ),
        UniqueConstraint(
            "session_id",
            "source_action_id",
            name="uq_world_event_trigger_evaluation_session_action",
        ),
    )


class WorldMemory(Base):
    __tablename__ = "world_memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id"), nullable=False, index=True
    )
    owner_agent_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    memory_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    source_action_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("world_actions.id"), nullable=True, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    privacy_category: Mapped[str] = mapped_column(
        String(30), nullable=False, default="ordinary"
    )
    occurred_day: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    session: Mapped[Session] = relationship(back_populates="world_memories")


class ScenarioInstance(Base):
    __tablename__ = "scenario_instances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id"), nullable=False, index=True
    )
    scenario_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    scenario_version: Mapped[str] = mapped_column(String(40), nullable=False)
    form: Mapped[str] = mapped_column(String(40), nullable=False)
    scenario_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active", index=True)
    location_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    variant: Mapped[str] = mapped_column(String(40), nullable=False, default="standard")
    assigned_agent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_day: Mapped[int] = mapped_column(Integer, nullable=False)
    started_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    follow_up_due_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    follow_up_due_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    follow_up_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="not_scheduled"
    )
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    session: Mapped[Session] = relationship(back_populates="scenario_instances")
    exposures: Mapped[list["ScenarioExposure"]] = relationship(
        back_populates="scenario", cascade="all, delete-orphan"
    )
    responses: Mapped[list["ScenarioResponse"]] = relationship(
        back_populates="scenario", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("session_id", "scenario_id", name="uq_scenario_session_key"),
    )


class ScenarioExposure(Base):
    __tablename__ = "scenario_exposures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id"), nullable=False, index=True
    )
    scenario_instance_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("scenario_instances.id"), nullable=False, index=True
    )
    stimulus_text: Mapped[str] = mapped_column(Text, nullable=False)
    visible_options_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    layout_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    exposure_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    interruption_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    world_day: Mapped[int] = mapped_column(Integer, nullable=False)
    world_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    scenario: Mapped[ScenarioInstance] = relationship(back_populates="exposures")


class ScenarioResponse(Base):
    __tablename__ = "scenario_responses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id"), nullable=False, index=True
    )
    scenario_instance_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("scenario_instances.id"), nullable=False, index=True
    )
    action_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("world_actions.id"), nullable=True, index=True
    )
    response_type: Mapped[str] = mapped_column(String(40), nullable=False)
    selected_option_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    response_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    response_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    changed_choice: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    outcome: Mapped[str] = mapped_column(String(80), nullable=False, default="recorded")
    world_day: Mapped[int] = mapped_column(Integer, nullable=False)
    world_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    scenario: Mapped[ScenarioInstance] = relationship(back_populates="responses")


class WorldConversation(Base):
    __tablename__ = "world_conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id"), nullable=False, index=True
    )
    agent_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    location_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    conversation_kind: Mapped[str] = mapped_column(
        String(30), nullable=False, default="participant_resident", index=True
    )
    initiator_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="participant"
    )
    initiator_agent_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True
    )
    visibility: Mapped[str] = mapped_column(
        String(20), nullable=False, default="session_private", index=True
    )
    ended_reason_code: Mapped[str | None] = mapped_column(
        String(80), nullable=True
    )
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    session: Mapped[Session] = relationship(back_populates="world_conversations")
    turns: Mapped[list["WorldConversationTurn"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    participants: Mapped[list["WorldConversationParticipant"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class WorldConversationParticipant(Base):
    __tablename__ = "world_conversation_participants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("world_conversations.id"), nullable=False, index=True
    )
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id"), nullable=False, index=True
    )
    member_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    agent_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    member_role: Mapped[str] = mapped_column(String(30), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    left_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    leave_reason_code: Mapped[str | None] = mapped_column(String(80), nullable=True)

    conversation: Mapped[WorldConversation] = relationship(
        back_populates="participants"
    )
    session: Mapped[Session] = relationship(
        back_populates="world_conversation_participants"
    )

    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "member_type",
            "agent_id",
            name="uq_world_conversation_participant_member",
        ),
    )


class WorldConversationTurn(Base):
    __tablename__ = "world_conversation_turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("world_conversations.id"), nullable=False, index=True
    )
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id"), nullable=False, index=True
    )
    source_action_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("world_actions.id"), nullable=False, index=True
    )
    speaker_type: Mapped[str] = mapped_column(String(20), nullable=False)
    speaker_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    world_day: Mapped[int] = mapped_column(Integer, nullable=False)
    world_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    response_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generation_mode: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model_provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    safety_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    conversation: Mapped[WorldConversation] = relationship(back_populates="turns")


class WorldInteractionPrompt(Base):
    """A versioned resident-initiated invitation awaiting participant input."""

    __tablename__ = "world_interaction_prompts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id"), nullable=False, index=True
    )
    initiator_agent_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    location_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    prompt_kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True
    )
    opening_text_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    allowed_responses_json: Mapped[str] = mapped_column(
        Text, nullable=False, default='["accept","later","decline"]'
    )
    created_day: Mapped[int] = mapped_column(Integer, nullable=False)
    created_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    expiry_day: Mapped[int] = mapped_column(Integer, nullable=False)
    expiry_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    resolved_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolved_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_intent_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("resident_intent_states.id"), nullable=True, index=True
    )
    source_pulse_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("world_simulation_pulses.id"), nullable=True, index=True
    )
    source_action_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("world_actions.id"), nullable=True, index=True
    )
    response_action_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("world_actions.id"), nullable=True, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    cooldown_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    cooldown_until_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cooldown_until_time_minutes: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    reason_code: Mapped[str] = mapped_column(
        String(80), nullable=False, default="awaiting_participant"
    )
    policy_id: Mapped[str] = mapped_column(String(80), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    session: Mapped[Session] = relationship(back_populates="world_interaction_prompts")

    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "idempotency_key",
            name="uq_world_interaction_prompt_session_key",
        ),
    )


class RelationshipState(Base):
    __tablename__ = "relationships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id"), nullable=False, index=True
    )
    source_agent_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    target_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    familiarity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trust: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warmth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tension: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unresolved_context: Mapped[str] = mapped_column(Text, nullable=False, default="")
    version: Mapped[str] = mapped_column(
        String(40), nullable=False, default="relationship-v1"
    )
    updated_day: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=540)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    session: Mapped[Session] = relationship(back_populates="relationships")
    changes: Mapped[list["RelationshipChange"]] = relationship(
        back_populates="relationship",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "source_agent_id",
            "target_key",
            name="uq_relationship_session_source_target",
        ),
        CheckConstraint("familiarity >= 0 AND familiarity <= 100"),
        CheckConstraint("trust >= -100 AND trust <= 100"),
        CheckConstraint("warmth >= -100 AND warmth <= 100"),
        CheckConstraint("tension >= 0 AND tension <= 100"),
    )


class RelationshipChange(Base):
    __tablename__ = "relationship_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id"), nullable=False, index=True
    )
    relationship_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("relationships.id"), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    source_action_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("world_actions.id"), nullable=True, index=True
    )
    source_event_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_event_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    effect_key: Mapped[str] = mapped_column(String(80), nullable=False)
    familiarity_delta: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trust_delta: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warmth_delta: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tension_delta: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    before_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    after_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    world_day: Mapped[int] = mapped_column(Integer, nullable=False)
    world_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)

    session: Mapped[Session] = relationship(back_populates="relationship_changes")
    relationship: Mapped[RelationshipState] = relationship(back_populates="changes")

    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "idempotency_key",
            name="uq_relationship_change_session_idempotency",
        ),
    )


class WorldCommitment(Base):
    """A deterministic in-world agreement derived from an authored activity recipe."""

    __tablename__ = "world_commitments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("sessions.id"), nullable=False, index=True)
    recipe_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="scheduled", index=True)
    location_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    organizer_type: Mapped[str] = mapped_column(String(20), nullable=False)
    organizer_agent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    participants_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    scheduled_day: Mapped[int] = mapped_column(Integer, nullable=False)
    scheduled_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    source_action_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("world_actions.id"), nullable=True, index=True)
    policy_id: Mapped[str] = mapped_column(String(80), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    runtime_version: Mapped[str] = mapped_column(
        String(80), nullable=False, default="legacy-activity-v1", index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    min_participants: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_participants: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    deadline_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deadline_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    object_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    role_slots_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    required_actor_keys_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )
    reschedule_generation: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    ended_reason_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class WorldPlanMember(Base):
    """One actor's explicit response and attendance in an M7 plan."""

    __tablename__ = "world_plan_members"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id"), nullable=False, index=True
    )
    commitment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("world_commitments.id"), nullable=False, index=True
    )
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_agent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    role_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    response_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="proposed", index=True
    )
    response_reason_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    attendance_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending", index=True
    )
    arrival_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    arrival_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    departure_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    departure_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    invited_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    __table_args__ = (
        UniqueConstraint(
            "commitment_id", "actor_key", name="uq_world_plan_member_actor"
        ),
    )


class WorldResourceReservation(Base):
    """Tentative or confirmed reservation owned by exactly one plan generation."""

    __tablename__ = "world_resource_reservations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id"), nullable=False, index=True
    )
    commitment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("world_commitments.id"), nullable=False, index=True
    )
    resource_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    resource_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    start_ordinal: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    end_ordinal: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    start_day: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    end_day: Mapped[int] = mapped_column(Integer, nullable=False)
    end_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="tentative", index=True
    )
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    released_reason_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "commitment_id",
            "resource_type",
            "resource_key",
            "generation",
            name="uq_world_reservation_generation_resource",
        ),
    )


class WorldPlanTransition(Base):
    """Idempotent audit record for every requested plan lifecycle transition."""

    __tablename__ = "world_plan_transitions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id"), nullable=False, index=True
    )
    commitment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("world_commitments.id"), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_agent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transition_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    requested_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    before_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    after_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    result_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    world_day: Mapped[int] = mapped_column(Integer, nullable=False)
    world_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)

    __table_args__ = (
        UniqueConstraint(
            "session_id", "idempotency_key", name="uq_world_plan_transition_key"
        ),
    )


class WorldPlanNotice(Base):
    """Durable participant/resident notice generated from a plan transition."""

    __tablename__ = "world_plan_notices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id"), nullable=False, index=True
    )
    commitment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("world_commitments.id"), nullable=False, index=True
    )
    transition_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("world_plan_transitions.id"), nullable=False, index=True
    )
    recipient_actor_key: Mapped[str] = mapped_column(
        String(80), nullable=False, index=True
    )
    notice_type: Mapped[str] = mapped_column(String(40), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    world_day: Mapped[int] = mapped_column(Integer, nullable=False)
    world_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)

    __table_args__ = (
        UniqueConstraint(
            "transition_id",
            "recipient_actor_key",
            "notice_type",
            name="uq_world_plan_notice_recipient",
        ),
    )


class WorldBoardPost(Base):
    __tablename__ = "world_board_posts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("sessions.id"), nullable=False, index=True)
    commitment_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("world_commitments.id"), nullable=True, index=True)
    author_type: Mapped[str] = mapped_column(String(20), nullable=False)
    author_agent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_json: Mapped[str] = mapped_column(Text, nullable=False)
    world_day: Mapped[int] = mapped_column(Integer, nullable=False)
    world_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class WorldPlanSocialProjection(Base):
    """One phone invitation (and optional board mirror) backed by one M7 plan."""

    __tablename__ = "world_plan_social_projections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id"), nullable=False, index=True
    )
    commitment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("world_commitments.id"), nullable=False, unique=True, index=True
    )
    invitation_post_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("user_posts.id"), nullable=False, unique=True, index=True
    )
    board_post_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("world_board_posts.id"), nullable=True, unique=True
    )
    audience_scope: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    audience_actor_keys_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    organizer_attending: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    wait_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    public_headcount: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    initial_plan_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    __table_args__ = (
        UniqueConstraint(
            "session_id", "idempotency_key", name="uq_world_plan_social_projection_key"
        ),
    )


class WorldKnowledgeFact(Base):
    """A provenance-bearing fact; visibility alone never grants actor knowledge."""

    __tablename__ = "world_knowledge_facts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id"), nullable=False, index=True
    )
    fact_key: Mapped[str] = mapped_column(String(180), nullable=False)
    fact_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    subject_type: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    visibility: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    world_day: Mapped[int] = mapped_column(Integer, nullable=False)
    world_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    __table_args__ = (
        UniqueConstraint("session_id", "fact_key", name="uq_world_knowledge_fact_key"),
    )


class WorldActorKnowledge(Base):
    """Evidence that one actor actually acquired one world fact."""

    __tablename__ = "world_actor_knowledge"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id"), nullable=False, index=True
    )
    fact_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("world_knowledge_facts.id"), nullable=False, index=True
    )
    actor_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    acquisition_source: Mapped[str] = mapped_column(String(30), nullable=False)
    source_post_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("user_posts.id"), nullable=True, index=True
    )
    world_day: Mapped[int] = mapped_column(Integer, nullable=False)
    world_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    __table_args__ = (
        UniqueConstraint("fact_id", "actor_key", name="uq_world_actor_knowledge_fact_actor"),
    )


class WorldSocialPostView(Base):
    """Idempotent proof that an actor opened a phone post."""

    __tablename__ = "world_social_post_views"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id"), nullable=False, index=True
    )
    user_post_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("user_posts.id"), nullable=False, index=True
    )
    viewer_actor_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    world_day: Mapped[int] = mapped_column(Integer, nullable=False)
    world_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    __table_args__ = (
        UniqueConstraint(
            "session_id", "idempotency_key", name="uq_world_social_post_view_key"
        ),
        UniqueConstraint(
            "user_post_id", "viewer_actor_key", name="uq_world_social_post_view_actor"
        ),
    )


class WorldPlanVariantProposal(Base):
    """A registered small-scale fallback awaiting every present actor's consent."""

    __tablename__ = "world_plan_variant_proposals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id"), nullable=False, index=True
    )
    commitment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("world_commitments.id"), nullable=False, index=True
    )
    source_recipe_id: Mapped[str] = mapped_column(String(128), nullable=False)
    target_recipe_id: Mapped[str] = mapped_column(String(128), nullable=False)
    proposer_actor_key: Mapped[str] = mapped_column(String(80), nullable=False)
    attendee_actor_keys_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="proposed", index=True)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    applied_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    world_day: Mapped[int] = mapped_column(Integer, nullable=False)
    world_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    __table_args__ = (
        UniqueConstraint(
            "session_id", "idempotency_key", name="uq_world_plan_variant_proposal_key"
        ),
    )


class WorldPlanVariantConsent(Base):
    __tablename__ = "world_plan_variant_consents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id"), nullable=False, index=True
    )
    proposal_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("world_plan_variant_proposals.id"), nullable=False, index=True
    )
    actor_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    world_day: Mapped[int] = mapped_column(Integer, nullable=False)
    world_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    __table_args__ = (
        UniqueConstraint("proposal_id", "actor_key", name="uq_world_plan_variant_consent_actor"),
        UniqueConstraint(
            "session_id", "idempotency_key", name="uq_world_plan_variant_consent_key"
        ),
    )


class WorldEmergenceDecision(Base):
    __tablename__ = "world_emergence_decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("sessions.id"), nullable=False, index=True)
    source_action_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("world_actions.id"), nullable=True, index=True)
    candidate_type: Mapped[str] = mapped_column(String(40), nullable=False)
    candidate_id: Mapped[str] = mapped_column(String(128), nullable=False)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    simulation_seed: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_id: Mapped[str] = mapped_column(String(80), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class WorldEmergenceEvaluation(Base):
    """One deterministic M7-E director pass over an authoritative world snapshot."""

    __tablename__ = "world_emergence_evaluations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id"), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    source_pulse_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("world_simulation_pulses.id"), nullable=True, index=True
    )
    world_day: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    world_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    simulation_seed: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_id: Mapped[str] = mapped_column(String(80), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    state_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    selected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    budget_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    result_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    __table_args__ = (
        UniqueConstraint(
            "session_id", "idempotency_key", name="uq_world_emergence_evaluation_key"
        ),
    )


class WorldEmergenceCandidate(Base):
    """Persisted selected or blocked candidate, including its evidence and reasons."""

    __tablename__ = "world_emergence_candidates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    evaluation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("world_emergence_evaluations.id"), nullable=False, index=True
    )
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id"), nullable=False, index=True
    )
    candidate_key: Mapped[str] = mapped_column(String(128), nullable=False)
    recipe_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    complexity: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    player_facing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    direct_participant_invite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    organizer_actor_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    location_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    scheduled_day: Mapped[int] = mapped_column(Integer, nullable=False)
    scheduled_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_day: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    chain_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_event_runtime_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("world_emergent_event_runtimes.id"), nullable=True, index=True
    )
    source_types_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    source_facts_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    invitees_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    validation_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    score_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    selected_commitment_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("world_commitments.id"), nullable=True, index=True
    )
    selected_event_instance_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("world_event_instances.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)

    __table_args__ = (
        UniqueConstraint(
            "evaluation_id", "candidate_key", name="uq_world_emergence_candidate_key"
        ),
    )


class WorldEmergentEventRuntime(Base):
    """M7-E lifecycle projection joining a selected candidate to its M7 plan."""

    __tablename__ = "world_emergent_event_runtimes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id"), nullable=False, index=True
    )
    candidate_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("world_emergence_candidates.id"), nullable=False, unique=True, index=True
    )
    event_instance_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("world_event_instances.id"), nullable=False, unique=True, index=True
    )
    commitment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("world_commitments.id"), nullable=False, unique=True, index=True
    )
    recipe_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    complexity: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    player_facing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    direct_participant_invite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    organizer_actor_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    chain_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fact_chain_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    started_day: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    started_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_day: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    terminal_reason_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class WorldEventStage(Base):
    """M7-F aggregate; membership and attendance stay exclusively in the plan."""

    __tablename__ = "world_event_stages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("sessions.id"), index=True)
    runtime_id: Mapped[int] = mapped_column(Integer, ForeignKey("world_emergent_event_runtimes.id"), unique=True, index=True)
    stage_recipe_id: Mapped[str] = mapped_column(String(128))
    definition_hash: Mapped[str] = mapped_column(String(64))
    definition_json: Mapped[str] = mapped_column(Text)
    current_stage_id: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(24), default="active")
    revision: Mapped[int] = mapped_column(Integer, default=0)
    entered_ordinal: Mapped[int] = mapped_column(Integer)
    deadline_ordinal: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str | None] = mapped_column(String(128), nullable=True)
    public_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    state_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class WorldEventStageOperation(Base):
    """Append-only decisions and action-backed contribution audit."""

    __tablename__ = "world_event_stage_operations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("sessions.id"), index=True)
    runtime_id: Mapped[int] = mapped_column(Integer, ForeignKey("world_emergent_event_runtimes.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    request_hash: Mapped[str] = mapped_column(String(64))
    actor_key: Mapped[str] = mapped_column(String(80))
    operation: Mapped[str] = mapped_column(String(30))
    stage_id: Mapped[str] = mapped_column(String(128))
    world_day: Mapped[int] = mapped_column(Integer)
    world_time_minutes: Mapped[int] = mapped_column(Integer)
    result_json: Mapped[str] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("session_id", "idempotency_key", name="uq_stage_operation_key"),)


class WorldDecisionInvocation(Base):
    """M7-G short-transaction reservation and minimal decision audit."""
    __tablename__ = "world_decision_invocations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("sessions.id"), index=True)
    actor_key: Mapped[str] = mapped_column(String(80), index=True)
    decision_type: Mapped[str] = mapped_column(String(40))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    request_hash: Mapped[str] = mapped_column(String(64))
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    world_day: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    provider_id: Mapped[str] = mapped_column(String(80))
    model_version: Mapped[str] = mapped_column(String(80))
    prompt_version: Mapped[str] = mapped_column(String(80))
    policy_version: Mapped[str] = mapped_column(String(80))
    generation_mode: Mapped[str] = mapped_column(String(30), default="rule_fallback")
    fallback_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    input_summary_json: Mapped[str] = mapped_column(Text, default="{}")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    __table_args__ = (UniqueConstraint("session_id", "idempotency_key", name="uq_decision_invocation_key"),)


class WorldDecisionAttempt(Base):
    """Conservative UTF-8 token-unit reservation; no raw provider I/O or secrets."""
    __tablename__ = "world_decision_attempts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("sessions.id"), index=True)
    invocation_id: Mapped[int] = mapped_column(Integer, ForeignKey("world_decision_invocations.id"), index=True)
    world_day: Mapped[int] = mapped_column(Integer)
    attempt_number: Mapped[int] = mapped_column(Integer)
    reserved_units: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), default="reserved")
    output_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (UniqueConstraint("invocation_id", "attempt_number", name="uq_decision_attempt_number"),)


class WorldEmergentEventTransition(Base):
    """Append-only audit of lifecycle reconciliation for an emergent event."""

    __tablename__ = "world_emergent_event_transitions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id"), nullable=False, index=True
    )
    runtime_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("world_emergent_event_runtimes.id"), nullable=False, index=True
    )
    transition_key: Mapped[str] = mapped_column(String(160), nullable=False)
    transition_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    before_status: Mapped[str] = mapped_column(String(24), nullable=False)
    after_status: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    world_day: Mapped[int] = mapped_column(Integer, nullable=False)
    world_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)

    __table_args__ = (
        UniqueConstraint(
            "runtime_id", "transition_key", name="uq_world_emergent_transition_key"
        ),
    )
