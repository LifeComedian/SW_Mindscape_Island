import os

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./demo.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    # Use NullPool for file databases so pool waits cannot block the event loop.
    **({"poolclass": NullPool} if DATABASE_URL.startswith('sqlite:') and ':memory:' not in DATABASE_URL and DATABASE_URL != 'sqlite://' else {}),
)


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    """Enforce declared foreign keys for every SQLite connection."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        # WAL permits readers during short writes; SQLite still has one writer.
        cursor.execute("PRAGMA journal_mode=WAL")
    finally:
        cursor.close()

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


class Base(DeclarativeBase):
    pass


def _column_names(connection, table_name: str) -> set[str]:
    rows = connection.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    return {row[1] for row in rows}


def _table_names(connection) -> set[str]:
    rows = connection.execute(
        text("SELECT name FROM sqlite_master WHERE type='table'")
    ).fetchall()
    return {row[0] for row in rows}


def upgrade_database_schema() -> None:
    """Add missing columns and indexes without removing existing data."""
    with engine.begin() as connection:
        table_names = _table_names(connection)
        session_columns = _column_names(connection, "sessions")
        session_additions = {
            "user_alias": "ALTER TABLE sessions ADD COLUMN user_alias VARCHAR(80) NOT NULL DEFAULT ''",
            "consent_version": "ALTER TABLE sessions ADD COLUMN consent_version VARCHAR(40) NOT NULL DEFAULT 'v0.2'",
            "status": "ALTER TABLE sessions ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'active'",
            "started_at": "ALTER TABLE sessions ADD COLUMN started_at DATETIME",
            "ended_at": "ALTER TABLE sessions ADD COLUMN ended_at DATETIME",
            "current_day": "ALTER TABLE sessions ADD COLUMN current_day INTEGER NOT NULL DEFAULT 1",
            "total_days": "ALTER TABLE sessions ADD COLUMN total_days INTEGER NOT NULL DEFAULT 7",
            "simulation_seed": "ALTER TABLE sessions ADD COLUMN simulation_seed INTEGER NOT NULL DEFAULT 0",
            "virtual_start_date": "ALTER TABLE sessions ADD COLUMN virtual_start_date DATE",
        }
        for column, statement in session_additions.items():
            if column not in session_columns:
                connection.execute(text(statement))

        connection.execute(
            text("UPDATE sessions SET user_alias = nickname WHERE user_alias = '' OR user_alias IS NULL")
        )
        connection.execute(
            text("UPDATE sessions SET started_at = created_at WHERE started_at IS NULL")
        )
        connection.execute(
            text(
                "UPDATE sessions SET virtual_start_date = date(started_at) "
                "WHERE virtual_start_date IS NULL"
            )
        )

        interaction_columns = _column_names(connection, "interactions")
        interaction_additions = {
            "event_type": "ALTER TABLE interactions ADD COLUMN event_type VARCHAR(30) NOT NULL DEFAULT 'like'",
            "agent_id": "ALTER TABLE interactions ADD COLUMN agent_id INTEGER",
            "parent_interaction_id": "ALTER TABLE interactions ADD COLUMN parent_interaction_id INTEGER",
            "parent_community_activity_id": "ALTER TABLE interactions ADD COLUMN parent_community_activity_id INTEGER",
            "created_at": "ALTER TABLE interactions ADD COLUMN created_at DATETIME",
            "response_latency_ms": "ALTER TABLE interactions ADD COLUMN response_latency_ms INTEGER",
            "generation_mode": "ALTER TABLE interactions ADD COLUMN generation_mode VARCHAR(40)",
            "model_provider": "ALTER TABLE interactions ADD COLUMN model_provider VARCHAR(80)",
            "model_name": "ALTER TABLE interactions ADD COLUMN model_name VARCHAR(120)",
            "prompt_version": "ALTER TABLE interactions ADD COLUMN prompt_version VARCHAR(80)",
            "safety_flag": "ALTER TABLE interactions ADD COLUMN safety_flag BOOLEAN NOT NULL DEFAULT 0",
            "metadata_json": "ALTER TABLE interactions ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'",
            "world_day": "ALTER TABLE interactions ADD COLUMN world_day INTEGER",
            "world_time_minutes": "ALTER TABLE interactions ADD COLUMN world_time_minutes INTEGER",
        }
        for column, statement in interaction_additions.items():
            if column not in interaction_columns:
                connection.execute(text(statement))

        connection.execute(
            text("UPDATE interactions SET event_type = action_type WHERE event_type = 'like' AND action_type IS NOT NULL")
        )
        connection.execute(
            text("UPDATE interactions SET created_at = timestamp WHERE created_at IS NULL")
        )

        community_activity_columns = _column_names(connection, "community_activities")
        community_activity_additions = {
            "response_latency_ms": "ALTER TABLE community_activities ADD COLUMN response_latency_ms INTEGER",
            "generation_mode": "ALTER TABLE community_activities ADD COLUMN generation_mode VARCHAR(40)",
            "model_provider": "ALTER TABLE community_activities ADD COLUMN model_provider VARCHAR(80)",
            "model_name": "ALTER TABLE community_activities ADD COLUMN model_name VARCHAR(120)",
            "prompt_version": "ALTER TABLE community_activities ADD COLUMN prompt_version VARCHAR(80)",
            "safety_flag": "ALTER TABLE community_activities ADD COLUMN safety_flag BOOLEAN NOT NULL DEFAULT 0",
            "metadata_json": "ALTER TABLE community_activities ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'",
            "world_day": "ALTER TABLE community_activities ADD COLUMN world_day INTEGER",
            "world_time_minutes": "ALTER TABLE community_activities ADD COLUMN world_time_minutes INTEGER",
        }
        for column, statement in community_activity_additions.items():
            if column not in community_activity_columns:
                connection.execute(text(statement))

        if "user_posts" in table_names:
            user_post_columns = _column_names(connection, "user_posts")
            user_post_additions = {
                "world_time_minutes": "ALTER TABLE user_posts ADD COLUMN world_time_minutes INTEGER",
                "author_type": "ALTER TABLE user_posts ADD COLUMN author_type VARCHAR(20) NOT NULL DEFAULT 'participant'",
                "author_agent_id": "ALTER TABLE user_posts ADD COLUMN author_agent_id INTEGER",
                "post_type": "ALTER TABLE user_posts ADD COLUMN post_type VARCHAR(30) NOT NULL DEFAULT 'personal'",
                "visibility": "ALTER TABLE user_posts ADD COLUMN visibility VARCHAR(30) NOT NULL DEFAULT 'island_public'",
                "source_type": "ALTER TABLE user_posts ADD COLUMN source_type VARCHAR(40)",
                "source_id": "ALTER TABLE user_posts ADD COLUMN source_id INTEGER",
                "location_id": "ALTER TABLE user_posts ADD COLUMN location_id VARCHAR(40)",
                "facts_json": "ALTER TABLE user_posts ADD COLUMN facts_json TEXT NOT NULL DEFAULT '{}'",
                "metadata_json": "ALTER TABLE user_posts ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'",
                "idempotency_key": "ALTER TABLE user_posts ADD COLUMN idempotency_key VARCHAR(120)",
            }
            for column, statement in user_post_additions.items():
                if column not in user_post_columns:
                    connection.execute(text(statement))

        if "notifications" in table_names:
            notification_columns = _column_names(connection, "notifications")
            notification_additions = {
                "world_day": "ALTER TABLE notifications ADD COLUMN world_day INTEGER",
                "world_time_minutes": "ALTER TABLE notifications ADD COLUMN world_time_minutes INTEGER",
            }
            for column, statement in notification_additions.items():
                if column not in notification_columns:
                    connection.execute(text(statement))

        world_action_columns = _column_names(connection, "world_actions")
        world_action_additions = {
            "actor_type": "ALTER TABLE world_actions ADD COLUMN actor_type VARCHAR(20) NOT NULL DEFAULT 'participant'",
            "actor_agent_id": "ALTER TABLE world_actions ADD COLUMN actor_agent_id INTEGER",
            "policy_id": "ALTER TABLE world_actions ADD COLUMN policy_id VARCHAR(80)",
            "policy_version": "ALTER TABLE world_actions ADD COLUMN policy_version VARCHAR(40)",
            "decision_reason_code": "ALTER TABLE world_actions ADD COLUMN decision_reason_code VARCHAR(80)",
            "event_instance_id": "ALTER TABLE world_actions ADD COLUMN event_instance_id INTEGER",
        }
        for column, statement in world_action_additions.items():
            if column not in world_action_columns:
                connection.execute(text(statement))

        if "world_atomic_action_executions" in table_names:
            atomic_execution_columns = _column_names(
                connection, "world_atomic_action_executions"
            )
            if "target_actor_type" not in atomic_execution_columns:
                connection.execute(
                    text(
                        "ALTER TABLE world_atomic_action_executions "
                        "ADD COLUMN target_actor_type VARCHAR(20)"
                    )
                )

        if "world_commitments" in table_names:
            commitment_columns = _column_names(connection, "world_commitments")
            commitment_additions = {
                "runtime_version": "ALTER TABLE world_commitments ADD COLUMN runtime_version VARCHAR(80) NOT NULL DEFAULT 'legacy-activity-v1'",
                "revision": "ALTER TABLE world_commitments ADD COLUMN revision INTEGER NOT NULL DEFAULT 0",
                "duration_minutes": "ALTER TABLE world_commitments ADD COLUMN duration_minutes INTEGER NOT NULL DEFAULT 0",
                "min_participants": "ALTER TABLE world_commitments ADD COLUMN min_participants INTEGER NOT NULL DEFAULT 1",
                "max_participants": "ALTER TABLE world_commitments ADD COLUMN max_participants INTEGER NOT NULL DEFAULT 20",
                "deadline_day": "ALTER TABLE world_commitments ADD COLUMN deadline_day INTEGER",
                "deadline_time_minutes": "ALTER TABLE world_commitments ADD COLUMN deadline_time_minutes INTEGER",
                "object_ids_json": "ALTER TABLE world_commitments ADD COLUMN object_ids_json TEXT NOT NULL DEFAULT '[]'",
                "role_slots_json": "ALTER TABLE world_commitments ADD COLUMN role_slots_json TEXT NOT NULL DEFAULT '[]'",
                "required_actor_keys_json": "ALTER TABLE world_commitments ADD COLUMN required_actor_keys_json TEXT NOT NULL DEFAULT '[]'",
                "reschedule_generation": "ALTER TABLE world_commitments ADD COLUMN reschedule_generation INTEGER NOT NULL DEFAULT 0",
                "ended_reason_code": "ALTER TABLE world_commitments ADD COLUMN ended_reason_code VARCHAR(80)",
                "updated_at": "ALTER TABLE world_commitments ADD COLUMN updated_at DATETIME",
            }
            for column, statement in commitment_additions.items():
                if column not in commitment_columns:
                    connection.execute(text(statement))
            connection.execute(
                text(
                    "UPDATE world_commitments SET updated_at = created_at "
                    "WHERE updated_at IS NULL"
                )
            )

        if "world_conversations" in table_names:
            conversation_columns = _column_names(connection, "world_conversations")
            conversation_additions = {
                "conversation_kind": "ALTER TABLE world_conversations ADD COLUMN conversation_kind VARCHAR(30) NOT NULL DEFAULT 'participant_resident'",
                "initiator_type": "ALTER TABLE world_conversations ADD COLUMN initiator_type VARCHAR(20) NOT NULL DEFAULT 'participant'",
                "initiator_agent_id": "ALTER TABLE world_conversations ADD COLUMN initiator_agent_id INTEGER",
                "visibility": "ALTER TABLE world_conversations ADD COLUMN visibility VARCHAR(20) NOT NULL DEFAULT 'session_private'",
                "ended_reason_code": "ALTER TABLE world_conversations ADD COLUMN ended_reason_code VARCHAR(80)",
                "metadata_json": "ALTER TABLE world_conversations ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'",
            }
            for column, statement in conversation_additions.items():
                if column not in conversation_columns:
                    connection.execute(text(statement))

        if "world_simulation_pulses" in table_names:
            pulse_columns = _column_names(connection, "world_simulation_pulses")
            if "result_snapshot_json" not in pulse_columns:
                connection.execute(
                    text(
                        "ALTER TABLE world_simulation_pulses "
                        "ADD COLUMN result_snapshot_json TEXT NOT NULL DEFAULT '{}'"
                    )
                )

        for emergence_table in (
            "world_emergence_candidates",
            "world_emergent_event_runtimes",
        ):
            if emergence_table in table_names:
                emergence_columns = _column_names(connection, emergence_table)
                if "direct_participant_invite" not in emergence_columns:
                    connection.execute(
                        text(
                            f"ALTER TABLE {emergence_table} ADD COLUMN "
                            "direct_participant_invite BOOLEAN NOT NULL DEFAULT 0"
                        )
                    )

        indexes = [
            "CREATE INDEX IF NOT EXISTS ix_sessions_status ON sessions (status)",
            "CREATE INDEX IF NOT EXISTS ix_interactions_event_type ON interactions (event_type)",
            "CREATE INDEX IF NOT EXISTS ix_interactions_created_at ON interactions (created_at)",
            "CREATE INDEX IF NOT EXISTS ix_interactions_post_id ON interactions (post_id)",
            "CREATE INDEX IF NOT EXISTS ix_interactions_agent_id ON interactions (agent_id)",
            "CREATE INDEX IF NOT EXISTS ix_interactions_parent_interaction_id ON interactions (parent_interaction_id)",
            "CREATE INDEX IF NOT EXISTS ix_interactions_parent_community_activity_id ON interactions (parent_community_activity_id)",
            "CREATE INDEX IF NOT EXISTS ix_interactions_world_day ON interactions (world_day)",
            "CREATE INDEX IF NOT EXISTS ix_community_activities_world_day ON community_activities (world_day)",
            "CREATE INDEX IF NOT EXISTS ix_world_actions_session_actor_type ON world_actions (session_id, actor_type)",
            "CREATE INDEX IF NOT EXISTS ix_world_actions_session_actor_agent_id ON world_actions (session_id, actor_agent_id)",
            "CREATE INDEX IF NOT EXISTS ix_world_actions_event_instance_id ON world_actions (event_instance_id)",
        ]
        if "world_commitments" in table_names:
            indexes.append(
                "CREATE INDEX IF NOT EXISTS ix_world_commitments_runtime_version "
                "ON world_commitments (runtime_version)"
            )
        if "world_resource_reservations" in table_names:
            indexes.extend(
                [
                    "CREATE INDEX IF NOT EXISTS ix_world_reservation_conflict "
                    "ON world_resource_reservations "
                    "(session_id, resource_type, resource_key, status, start_ordinal, end_ordinal)",
                    "CREATE INDEX IF NOT EXISTS ix_world_reservation_plan_generation "
                    "ON world_resource_reservations (commitment_id, generation, status)",
                ]
            )
        if "world_plan_social_projections" in table_names:
            indexes.append(
                "CREATE INDEX IF NOT EXISTS ix_world_plan_social_projection_session_scope "
                "ON world_plan_social_projections (session_id, audience_scope)"
            )
        if "world_actor_knowledge" in table_names:
            indexes.append(
                "CREATE INDEX IF NOT EXISTS ix_world_actor_knowledge_session_actor "
                "ON world_actor_knowledge (session_id, actor_key)"
            )
        if "relationships" in table_names:
            indexes.extend(
                [
                    "CREATE INDEX IF NOT EXISTS ix_relationships_session_source ON relationships (session_id, source_agent_id)",
                    "CREATE INDEX IF NOT EXISTS ix_relationships_session_target ON relationships (session_id, target_key)",
                ]
            )
        if "relationship_changes" in table_names:
            indexes.extend(
                [
                    "CREATE INDEX IF NOT EXISTS ix_relationship_changes_session_relationship ON relationship_changes (session_id, relationship_id)",
                    "CREATE INDEX IF NOT EXISTS ix_relationship_changes_session_source_action ON relationship_changes (session_id, source_action_id)",
                    "CREATE INDEX IF NOT EXISTS ix_relationship_changes_session_reason ON relationship_changes (session_id, reason_code)",
                ]
            )
        if "world_event_instances" in table_names:
            indexes.extend(
                [
                    "CREATE INDEX IF NOT EXISTS ix_world_event_instances_session_status ON world_event_instances (session_id, status)",
                    "CREATE INDEX IF NOT EXISTS ix_world_event_instances_session_location_status ON world_event_instances (session_id, location_id, status)",
                    "CREATE INDEX IF NOT EXISTS ix_world_event_instances_session_type_version ON world_event_instances (session_id, event_type, event_version)",
                ]
            )
        if "world_scheduled_events" in table_names:
            indexes.extend(
                [
                    "CREATE INDEX IF NOT EXISTS ix_world_scheduled_events_session_status_due ON world_scheduled_events (session_id, status, due_day, due_time_minutes)",
                    "CREATE INDEX IF NOT EXISTS ix_world_scheduled_events_parent_event ON world_scheduled_events (parent_event_instance_id)",
                    "CREATE INDEX IF NOT EXISTS ix_world_scheduled_events_result_event ON world_scheduled_events (result_event_instance_id)",
                ]
            )
        if "world_event_trigger_evaluations" in table_names:
            indexes.extend(
                [
                    "CREATE INDEX IF NOT EXISTS ix_world_event_trigger_evaluations_session_time ON world_event_trigger_evaluations (session_id, world_day, world_time_minutes)",
                    "CREATE INDEX IF NOT EXISTS ix_world_event_trigger_evaluations_session_outcome ON world_event_trigger_evaluations (session_id, outcome)",
                    "CREATE INDEX IF NOT EXISTS ix_world_event_trigger_evaluations_selected_event ON world_event_trigger_evaluations (selected_event_instance_id)",
                ]
            )
        if "world_conversations" in table_names:
            indexes.extend(
                [
                    "CREATE INDEX IF NOT EXISTS ix_world_conversations_session_kind_status ON world_conversations (session_id, conversation_kind, status)",
                    "CREATE INDEX IF NOT EXISTS ix_world_conversations_session_visibility_location ON world_conversations (session_id, visibility, location_id)",
                    "CREATE INDEX IF NOT EXISTS ix_world_conversations_initiator_agent_id ON world_conversations (initiator_agent_id)",
                ]
            )
        if "user_posts" in table_names:
            indexes.extend(
                [
                    "CREATE INDEX IF NOT EXISTS ix_user_posts_session_world_time ON user_posts (session_id, day, world_time_minutes)",
                    "CREATE INDEX IF NOT EXISTS ix_user_posts_session_author ON user_posts (session_id, author_type, author_agent_id)",
                    "CREATE UNIQUE INDEX IF NOT EXISTS ix_user_posts_session_idempotency ON user_posts (session_id, idempotency_key) WHERE idempotency_key IS NOT NULL",
                ]
            )
        if "notifications" in table_names:
            indexes.append(
                "CREATE INDEX IF NOT EXISTS ix_notifications_world_day ON notifications (world_day)"
            )
        if "world_conversation_participants" in table_names:
            indexes.extend(
                [
                    "CREATE INDEX IF NOT EXISTS ix_world_conversation_participants_session_agent ON world_conversation_participants (session_id, agent_id)",
                    "CREATE INDEX IF NOT EXISTS ix_world_conversation_participants_conversation ON world_conversation_participants (conversation_id)",
                ]
            )
        if "world_simulation_pulses" in table_names:
            indexes.extend(
                [
                    "CREATE INDEX IF NOT EXISTS ix_world_simulation_pulses_session_status ON world_simulation_pulses (session_id, status)",
                    "CREATE INDEX IF NOT EXISTS ix_world_simulation_pulses_session_created ON world_simulation_pulses (session_id, created_at)",
                ]
            )
        if "world_emergence_evaluations" in table_names:
            indexes.extend(
                [
                    "CREATE INDEX IF NOT EXISTS ix_world_emergence_evaluation_session_day "
                    "ON world_emergence_evaluations (session_id, world_day, status)",
                    "CREATE INDEX IF NOT EXISTS ix_world_emergence_evaluation_fingerprint "
                    "ON world_emergence_evaluations (session_id, state_fingerprint)",
                ]
            )
        if "world_emergence_candidates" in table_names:
            indexes.append(
                "CREATE INDEX IF NOT EXISTS ix_world_emergence_candidate_session_outcome "
                "ON world_emergence_candidates (session_id, outcome, reason_code)"
            )
        if "world_emergent_event_runtimes" in table_names:
            indexes.append(
                "CREATE INDEX IF NOT EXISTS ix_world_emergent_runtime_session_day_status "
                "ON world_emergent_event_runtimes (session_id, started_day, status)"
            )
        if "resident_intent_states" in table_names:
            indexes.extend(
                [
                    "CREATE INDEX IF NOT EXISTS ix_resident_intent_states_session_status ON resident_intent_states (session_id, status)",
                    "CREATE INDEX IF NOT EXISTS ix_resident_intent_states_session_agent ON resident_intent_states (session_id, agent_id)",
                    "CREATE INDEX IF NOT EXISTS ix_resident_intent_states_source_pulse ON resident_intent_states (source_pulse_id)",
                    "CREATE INDEX IF NOT EXISTS ix_resident_intent_states_source_action ON resident_intent_states (source_action_id)",
                ]
            )
        if "world_interaction_prompts" in table_names:
            indexes.extend(
                [
                    "CREATE INDEX IF NOT EXISTS ix_world_interaction_prompts_session_status ON world_interaction_prompts (session_id, status)",
                    "CREATE INDEX IF NOT EXISTS ix_world_interaction_prompts_session_location_status ON world_interaction_prompts (session_id, location_id, status)",
                    "CREATE INDEX IF NOT EXISTS ix_world_interaction_prompts_session_agent ON world_interaction_prompts (session_id, initiator_agent_id)",
                    "CREATE INDEX IF NOT EXISTS ix_world_interaction_prompts_source_pulse ON world_interaction_prompts (source_pulse_id)",
                    "CREATE INDEX IF NOT EXISTS ix_world_interaction_prompts_source_action ON world_interaction_prompts (source_action_id)",
                    "CREATE INDEX IF NOT EXISTS ix_world_interaction_prompts_response_action ON world_interaction_prompts (response_action_id)",
                    "CREATE INDEX IF NOT EXISTS ix_world_interaction_prompts_cooldown ON world_interaction_prompts (session_id, cooldown_key)",
                ]
            )
        for statement in indexes:
            connection.execute(text(statement))
