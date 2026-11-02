"""Content schemas for emergent events."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal, Mapping

from world.specs import LocalizedText, WorldSpecValidationError


MODULAR_SYSTEMS_CONTRACT_VERSION = "modular-emergence-authoring-v1"

ActorType = Literal["participant", "resident"]
TargetType = Literal[
    "none",
    "location",
    "object",
    "resident",
    "participant",
    "activity",
]
ActivityComplexity = Literal["ordinary", "coordinated", "major"]
AtomicActionExecutionMode = Literal["execute", "proposal"]
AtomicActionLocationScope = Literal["actor_location", "co_located"]
AtomicInputValueType = Literal["boolean", "integer", "identifier", "free_text", "object_command"]

PLAN_STATES = (
    "proposed",
    "accepted",
    "rejected",
    "cancelled",
    "expired",
    "in_progress",
    "completed",
    "failed",
)
ACTOR_AVAILABILITY_CHECK_TYPES = (
    "schedule",
    "location_open",
    "route_reachable",
    "actor_state",
    "active_conversation",
    "commitment",
)
PLAN_CONFLICT_CHECK_TYPES = (
    "actor_overlap",
    "location_capacity",
    "object_reservation",
    "travel_time",
)
KNOWLEDGE_SOURCE_TYPES = (
    "experienced",
    "public_post",
    "direct_message",
    "explicitly_told",
    "system_public_fact",
)
KNOWLEDGE_VISIBILITY_LEVELS = ("private", "targeted", "island_public")
CANDIDATE_SOURCE_TYPES = (
    "actor_goal",
    "memory",
    "relationship",
    "public_knowledge",
    "affordance",
    "commitment",
    "plan_conflict",
    "activity_recipe",
    "world_outcome",
)
ACTIVITY_COMPLEXITIES = ("ordinary", "coordinated", "major")
ACTION_FAILURE_REASON_CODES = (
    "actor_unavailable",
    "target_unavailable",
    "location_closed",
    "route_unreachable",
    "permission_denied",
    "capability_missing",
    "participant_bounds_unsatisfied",
    "plan_conflict",
    "resource_conflict",
    "budget_exhausted",
    "cooldown_active",
    "stale_revision",
    "idempotency_conflict",
    "interrupted",
    "technical_failure",
    "unknown_reference",
)
ATOMIC_EFFECT_TYPES = ("set_object_state", "set_world_flag")

# Content may lower these ceilings; zero disables the event class.
MAX_NEW_PLAYER_FACING_EVENTS_PER_DAY = 3
MAX_NEW_MAJOR_EVENTS_PER_DAY = 1
MAX_CONCURRENT_PLAYER_FACING_EVENTS = 2
MAX_DIRECT_AGENT_INVITATIONS_PER_DAY = 2
MAX_OPEN_COMMITMENTS_PER_ACTOR = 3
MAX_STAGES_PER_EVENT = 3
MAX_PLAYER_CHOICES_PER_STAGE = 4


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _require_unique(values: tuple[str, ...], *, label: str) -> None:
    if len(values) != len(set(values)):
        raise WorldSpecValidationError(f"{label} must be unique.")


@dataclass(frozen=True)
class AtomicActionInputSpec:
    input_id: str
    value_type: AtomicInputValueType
    required: bool
    allowed_values: tuple[str, ...] = ()
    minimum: int | None = None
    maximum: int | None = None
    max_length: int | None = None

    def __post_init__(self) -> None:
        if not self.input_id:
            raise WorldSpecValidationError("Atomic action inputs require an id.")
        _require_unique(self.allowed_values, label="allowed_values")
        if self.value_type == "integer":
            if (
                self.minimum is not None
                and self.maximum is not None
                and self.minimum > self.maximum
            ):
                raise WorldSpecValidationError(
                    "Atomic integer input minimum must not exceed maximum."
                )
        elif self.minimum is not None or self.maximum is not None:
            raise WorldSpecValidationError(
                "Only integer inputs may declare minimum or maximum."
            )
        if self.value_type in ("free_text", "object_command"):
            if self.max_length is None or not 1 <= self.max_length <= (180000 if self.value_type=="object_command" else 2000):
                raise WorldSpecValidationError(
                    "Free-text inputs require max_length between 1 and 2000."
                )
        elif self.max_length is not None:
            raise WorldSpecValidationError(
                "Only free-text inputs may declare max_length."
            )
        if self.allowed_values and self.value_type != "identifier":
            raise WorldSpecValidationError(
                "Only identifier inputs may declare allowed_values."
            )


@dataclass(frozen=True)
class AtomicActionContractSpec:
    action_id: str
    label: LocalizedText
    actor_types: tuple[ActorType, ...]
    target_types: tuple[TargetType, ...]
    duration_minutes: int
    consequences: tuple[Mapping[str, Any], ...]
    inputs: tuple[AtomicActionInputSpec, ...] = ()
    execution_mode: AtomicActionExecutionMode = "execute"
    location_scope: AtomicActionLocationScope = "co_located"
    min_participants: int = 1
    max_participants: int = 20
    preconditions: Mapping[str, Any] = field(default_factory=dict)
    effect_allowlist: tuple[str, ...] = ()
    permission_keys: tuple[str, ...] = ()
    capability_keys: tuple[str, ...] = ()
    interruptible: bool = True
    failure_reason_codes: tuple[str, ...] = ()
    text_record: str | None = None

    def __post_init__(self) -> None:
        if not self.action_id or not self.actor_types or not self.target_types:
            raise WorldSpecValidationError(
                "Atomic actions require an id, actor types, and target types."
            )
        if not 0 <= self.duration_minutes <= 240:
            raise WorldSpecValidationError(
                "Atomic action duration_minutes must be between 0 and 240."
            )
        if not 1 <= self.min_participants <= self.max_participants <= 20:
            raise WorldSpecValidationError(
                "Atomic action participant bounds must satisfy 1 <= min <= max <= 20."
            )
        for label, values in (
            ("actor_types", self.actor_types),
            ("target_types", self.target_types),
            ("permission_keys", self.permission_keys),
            ("capability_keys", self.capability_keys),
            ("failure_reason_codes", self.failure_reason_codes),
            ("effect_allowlist", self.effect_allowlist),
        ):
            _require_unique(values, label=label)
        _require_unique(tuple(item.input_id for item in self.inputs), label="input_id")
        if set(self.failure_reason_codes) - set(ACTION_FAILURE_REASON_CODES):
            raise WorldSpecValidationError(
                "Atomic action contains an unsupported failure reason code."
            )
        if set(self.effect_allowlist) - set(ATOMIC_EFFECT_TYPES):
            raise WorldSpecValidationError(
                "Atomic action contains an unsupported effect type."
            )
        consequence_types = {
            str(item.get("effect_type", "")) for item in self.consequences
        }
        if not consequence_types <= set(self.effect_allowlist):
            raise WorldSpecValidationError(
                "Atomic action consequence is outside its effect allowlist."
            )
        if self.execution_mode == "proposal":
            if self.duration_minutes != 0:
                raise WorldSpecValidationError(
                    "Proposal actions must have duration_minutes=0."
                )
            if self.consequences or self.effect_allowlist:
                raise WorldSpecValidationError(
                    "Proposal actions cannot declare world-state effects."
                )
        elif any(item.value_type == "free_text" for item in self.inputs) and self.text_record is None:
            raise WorldSpecValidationError(
                "Free text is allowed only for proposal actions."
            )
        if self.text_record is not None:
            if self.text_record not in ("private_note", "public_note") or self.actor_types != ("participant",) or self.execution_mode != "execute":
                raise WorldSpecValidationError("Text records require a participant-authored note action.")
            fields = {i.input_id: i for i in self.inputs}
            expected = {self.text_record} | ({"publish"} if self.text_record == "public_note" else set())
            if set(fields) != expected or fields[self.text_record].value_type != "free_text" or not fields[self.text_record].required or (fields[self.text_record].max_length or 0) > 500:
                raise WorldSpecValidationError("Text record inputs must use the bounded note schema.")
            if self.text_record == "public_note" and (fields["publish"].value_type != "boolean" or not fields["publish"].required):
                raise WorldSpecValidationError("Public notes require explicit publication permission.")
        object.__setattr__(self, "label", _freeze(self.label))
        object.__setattr__(self, "inputs", tuple(self.inputs))
        object.__setattr__(self, "preconditions", _freeze(self.preconditions))
        object.__setattr__(
            self,
            "consequences",
            tuple(_freeze(item) for item in self.consequences),
        )


@dataclass(frozen=True)
class AffordanceContractSpec:
    affordance_id: str
    action_id: str
    location_ids: tuple[str, ...]
    object_ids: tuple[str, ...]
    enabled: bool
    conditions: Mapping[str, Any]
    permission_keys: tuple[str, ...] = ()
    capability_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.affordance_id or not self.action_id:
            raise WorldSpecValidationError("Affordances require ids.")
        for label, values in (
            ("location_ids", self.location_ids),
            ("object_ids", self.object_ids),
            ("permission_keys", self.permission_keys),
            ("capability_keys", self.capability_keys),
        ):
            _require_unique(values, label=label)
        object.__setattr__(self, "conditions", _freeze(self.conditions))


@dataclass(frozen=True)
class ActivityRecipeContractSpec:
    recipe_id: str
    label: LocalizedText
    location_ids: tuple[str, ...]
    action_ids: tuple[str, ...]
    object_ids: tuple[str, ...]
    role_slots: tuple[str, ...]
    variant_recipe_ids: tuple[str, ...]
    min_participants: int
    max_participants: int
    duration_minutes: int
    complexity: ActivityComplexity
    player_facing: bool
    conditions: Mapping[str, Any]
    board_post_template: LocalizedText | None = None

    def __post_init__(self) -> None:
        if not self.recipe_id or not self.location_ids or not self.action_ids:
            raise WorldSpecValidationError(
                "Activity recipes require an id, locations, and actions."
            )
        if not 1 <= self.min_participants <= self.max_participants <= 20:
            raise WorldSpecValidationError(
                "Activity participant bounds must satisfy 1 <= min <= max <= 20."
            )
        if not 0 <= self.duration_minutes <= 480:
            raise WorldSpecValidationError(
                "Activity duration_minutes must be between 0 and 480."
            )
        for label, values in (
            ("location_ids", self.location_ids),
            ("action_ids", self.action_ids),
            ("object_ids", self.object_ids),
            ("role_slots", self.role_slots),
            ("variant_recipe_ids", self.variant_recipe_ids),
        ):
            _require_unique(values, label=label)
        object.__setattr__(self, "label", _freeze(self.label))
        object.__setattr__(self, "conditions", _freeze(self.conditions))
        if self.board_post_template is not None:
            object.__setattr__(
                self,
                "board_post_template",
                _freeze(self.board_post_template),
            )


@dataclass(frozen=True)
class StageRecipeContractSpec:
    stage_recipe_id: str
    label: LocalizedText
    allowed_action_ids: tuple[str, ...]
    terminal_outcomes: tuple[str, ...]
    max_stages: int
    max_player_choices_per_stage: int
    initial_stage_id: str | None = None
    stages: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if (
            not self.stage_recipe_id
            or not self.allowed_action_ids
            or not self.terminal_outcomes
        ):
            raise WorldSpecValidationError(
                "Stage recipes require an id, actions, and terminal outcomes."
            )
        if not 1 <= self.max_stages <= MAX_STAGES_PER_EVENT:
            raise WorldSpecValidationError(
                f"Stage recipes may contain at most {MAX_STAGES_PER_EVENT} stages."
            )
        if not 1 <= self.max_player_choices_per_stage <= MAX_PLAYER_CHOICES_PER_STAGE:
            raise WorldSpecValidationError(
                "Stage recipes exceed the player-choice safety ceiling."
            )
        _require_unique(self.allowed_action_ids, label="allowed_action_ids")
        _require_unique(self.terminal_outcomes, label="terminal_outcomes")
        object.__setattr__(self, "label", _freeze(self.label))
        object.__setattr__(self, "stages", tuple(_freeze(item) for item in self.stages))


@dataclass(frozen=True)
class EmergenceBudgetSpec:
    policy_id: str
    policy_version: str
    max_agent_actions_per_tick: int
    max_invitations_per_tick: int
    max_activity_creations_per_tick: int
    max_event_chain_depth: int
    max_new_player_facing_events_per_day: int
    max_new_major_events_per_day: int
    max_concurrent_player_facing_events: int
    max_direct_agent_invitations_to_player_per_day: int
    max_open_commitments_per_actor: int
    same_recipe_daily_limit: int
    declined_pair_cooldown_minutes: int

    def __post_init__(self) -> None:
        ceilings = {
            "max_new_player_facing_events_per_day": (
                self.max_new_player_facing_events_per_day,
                MAX_NEW_PLAYER_FACING_EVENTS_PER_DAY,
            ),
            "max_new_major_events_per_day": (
                self.max_new_major_events_per_day,
                MAX_NEW_MAJOR_EVENTS_PER_DAY,
            ),
            "max_concurrent_player_facing_events": (
                self.max_concurrent_player_facing_events,
                MAX_CONCURRENT_PLAYER_FACING_EVENTS,
            ),
            "max_direct_agent_invitations_to_player_per_day": (
                self.max_direct_agent_invitations_to_player_per_day,
                MAX_DIRECT_AGENT_INVITATIONS_PER_DAY,
            ),
            "max_open_commitments_per_actor": (
                self.max_open_commitments_per_actor,
                MAX_OPEN_COMMITMENTS_PER_ACTOR,
            ),
        }
        for label, (value, ceiling) in ceilings.items():
            if not 0 <= value <= ceiling:
                raise WorldSpecValidationError(
                    f"{label} must be between 0 and {ceiling}."
                )


@dataclass(frozen=True)
class PlanPolicySpec:
    policy_id: str
    policy_version: str
    states: tuple[str, ...]
    actor_availability_checks: tuple[str, ...]
    conflict_checks: tuple[str, ...]
    travel_time_required: bool
    explicit_change_required: bool
    release_reservation_on_terminal: bool

    def __post_init__(self) -> None:
        if self.states != PLAN_STATES:
            raise WorldSpecValidationError(
                "Plan policy states must match the canonical lifecycle order."
            )
        if self.actor_availability_checks != ACTOR_AVAILABILITY_CHECK_TYPES:
            raise WorldSpecValidationError(
                "Actor availability checks must match the canonical order."
            )
        if self.conflict_checks != PLAN_CONFLICT_CHECK_TYPES:
            raise WorldSpecValidationError(
                "Plan conflict checks must match the canonical order."
            )
        if not (
            self.travel_time_required
            and self.explicit_change_required
            and self.release_reservation_on_terminal
        ):
            raise WorldSpecValidationError(
                "M7 plans must account for travel, explicit changes, and terminal cleanup."
            )


@dataclass(frozen=True)
class KnowledgePolicySpec:
    policy_id: str
    policy_version: str
    allowed_source_types: tuple[str, ...]
    visibility_levels: tuple[str, ...]
    require_provenance: bool
    prevent_omniscient_propagation: bool

    def __post_init__(self) -> None:
        if not self.allowed_source_types or set(self.allowed_source_types) - set(
            KNOWLEDGE_SOURCE_TYPES
        ):
            raise WorldSpecValidationError("Knowledge policy contains an invalid source type.")
        if self.visibility_levels != KNOWLEDGE_VISIBILITY_LEVELS:
            raise WorldSpecValidationError(
                "Knowledge visibility levels must match the canonical order."
            )
        _require_unique(self.allowed_source_types, label="allowed_source_types")
        if not self.require_provenance or not self.prevent_omniscient_propagation:
            raise WorldSpecValidationError(
                "M7 knowledge must retain provenance and prevent omniscient propagation."
            )


@dataclass(frozen=True)
class CandidatePolicySpec:
    policy_id: str
    policy_version: str
    allowed_source_types: tuple[str, ...]
    allowed_complexities: tuple[str, ...]
    llm_candidate_only: bool
    fail_closed_unknown_ids: bool
    max_candidates_per_evaluation: int

    def __post_init__(self) -> None:
        if not self.allowed_source_types or set(self.allowed_source_types) - set(
            CANDIDATE_SOURCE_TYPES
        ):
            raise WorldSpecValidationError("Candidate policy contains an invalid source type.")
        if not self.allowed_complexities or set(self.allowed_complexities) - set(
            ACTIVITY_COMPLEXITIES
        ):
            raise WorldSpecValidationError("Candidate policy contains an invalid complexity.")
        if not 1 <= self.max_candidates_per_evaluation <= 20:
            raise WorldSpecValidationError(
                "max_candidates_per_evaluation must be between 1 and 20."
            )
        if not self.llm_candidate_only or not self.fail_closed_unknown_ids:
            raise WorldSpecValidationError(
                "M7 authoring must keep model output candidate-only and fail closed."
            )
        _require_unique(self.allowed_source_types, label="allowed_source_types")
        _require_unique(self.allowed_complexities, label="allowed_complexities")


@dataclass(frozen=True)
class ModularSystemsContractSpec:
    contract_version: str
    actions: tuple[AtomicActionContractSpec, ...]
    affordances: tuple[AffordanceContractSpec, ...]
    activity_recipes: tuple[ActivityRecipeContractSpec, ...]
    stage_recipes: tuple[StageRecipeContractSpec, ...]
    emergence_policy: EmergenceBudgetSpec
    plan_policy: PlanPolicySpec
    knowledge_policy: KnowledgePolicySpec
    candidate_policy: CandidatePolicySpec

    def __post_init__(self) -> None:
        if self.contract_version != MODULAR_SYSTEMS_CONTRACT_VERSION:
            raise WorldSpecValidationError(
                f"contract_version must be {MODULAR_SYSTEMS_CONTRACT_VERSION}."
            )
        for label, values in (
            ("action_id", tuple(item.action_id for item in self.actions)),
            ("affordance_id", tuple(item.affordance_id for item in self.affordances)),
            ("recipe_id", tuple(item.recipe_id for item in self.activity_recipes)),
            (
                "stage_recipe_id",
                tuple(item.stage_recipe_id for item in self.stage_recipes),
            ),
        ):
            _require_unique(values, label=label)
