"""Validate action requests and build plans for the service layer to commit."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from world.emergence_contracts import (
    ACTION_FAILURE_REASON_CODES,
    ATOMIC_EFFECT_TYPES,
    MODULAR_SYSTEMS_CONTRACT_VERSION,
)


ATOMIC_ACTION_RUNTIME_VERSION = "atomic-action-runtime-v1"


class AtomicActionRuntimeError(RuntimeError):
    def __init__(self, detail: str, *, reason_code: str, status_code: int = 409) -> None:
        super().__init__(detail)
        self.detail = detail
        self.reason_code = reason_code
        self.status_code = status_code


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class AtomicActorSnapshot:
    actor_type: str
    agent_id: int | None
    location_id: str
    available: bool = True
    permissions: frozenset[str] = frozenset()
    capabilities: frozenset[str] = frozenset()
    state: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.actor_type not in {"participant", "resident"}:
            raise AtomicActionRuntimeError(
                "Atomic actor type is unsupported.",
                reason_code="unknown_reference",
            )
        if self.actor_type == "participant" and self.agent_id is not None:
            raise AtomicActionRuntimeError(
                "Participant actor cannot have an agent id.",
                reason_code="unknown_reference",
            )
        if self.actor_type == "resident" and self.agent_id is None:
            raise AtomicActionRuntimeError(
                "Resident actor requires an agent id.",
                reason_code="unknown_reference",
            )
        object.__setattr__(self, "state", _freeze(self.state))

    @property
    def actor_key(self) -> str:
        return "participant" if self.actor_type == "participant" else f"resident:{self.agent_id}"


@dataclass(frozen=True)
class AtomicActionTarget:
    location_id: str | None = None
    object_id: str | None = None
    agent_id: int | None = None
    actor_type: str | None = None

    @property
    def target_type(self) -> str:
        if self.object_id is not None:
            return "object"
        if self.actor_type == "participant":
            return "participant"
        if self.agent_id is not None:
            return self.actor_type or "resident"
        if self.location_id is not None:
            return "location"
        return "none"


@dataclass(frozen=True)
class AtomicRuntimeContext:
    revision: int
    location_open: bool
    participant_count: int
    known_object_ids: frozenset[str]
    known_resident_ids: frozenset[int] = frozenset()
    participant_present: bool = False
    stage_authorized: bool = False
    object_states: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.revision < 0:
            raise AtomicActionRuntimeError(
                "Atomic revision cannot be negative.",
                reason_code="stale_revision",
            )
        object.__setattr__(self, "object_states", _freeze(self.object_states))


@dataclass(frozen=True)
class AtomicActionCandidate:
    action_id: str
    affordance_id: str
    label: Mapping[str, str]
    execution_mode: str
    target: AtomicActionTarget
    duration_minutes: int
    input_definitions: tuple[Mapping[str, Any], ...]
    available: bool
    reason_code: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "label", _freeze(self.label))
        object.__setattr__(
            self,
            "input_definitions",
            tuple(_freeze(item) for item in self.input_definitions),
        )


@dataclass(frozen=True)
class PreparedAtomicAction:
    runtime_version: str
    action_id: str
    affordance_id: str
    execution_mode: str
    duration_minutes: int
    target: AtomicActionTarget
    normalized_inputs: Mapping[str, Any]
    effects: tuple[Mapping[str, Any], ...]
    interruptible: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "normalized_inputs", _freeze(self.normalized_inputs))
        object.__setattr__(
            self,
            "effects",
            tuple(_freeze(item) for item in self.effects),
        )


def _contains_state(actual: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    return all(actual.get(key) == value for key, value in expected.items())


def _reason(detail: str, code: str) -> AtomicActionRuntimeError:
    if code not in ACTION_FAILURE_REASON_CODES:
        code = "unknown_reference"
    return AtomicActionRuntimeError(detail, reason_code=code)


class AtomicActionRegistry:
    """Read-only action/affordance index built from one world specification."""

    def __init__(self, systems: Mapping[str, Any]) -> None:
        self.contract_version = str(systems.get("contract_version") or "legacy-v4")
        self.runtime_version = ATOMIC_ACTION_RUNTIME_VERSION
        self.modular_enabled = (
            self.contract_version == MODULAR_SYSTEMS_CONTRACT_VERSION
        )
        actions: dict[str, Mapping[str, Any]] = {}
        for raw in systems.get("action_definitions", ()):
            item = dict(raw)
            action_id = str(item.get("action_id") or "")
            if not action_id or action_id in actions:
                raise _reason("Atomic action registry contains an invalid action id.", "unknown_reference")
            actions[action_id] = _freeze(item)
        self.actions = MappingProxyType(actions)
        self.affordances = tuple(_freeze(dict(item)) for item in systems.get("affordances", ()))

    def _definition(self, action_id: str) -> Mapping[str, Any]:
        definition = self.actions.get(action_id)
        if definition is None:
            raise _reason("Atomic action id is not registered.", "unknown_reference")
        return definition

    def _matching_affordances(
        self,
        *,
        action_id: str,
        actor: AtomicActorSnapshot,
        target: AtomicActionTarget,
    ) -> tuple[Mapping[str, Any], ...]:
        matches = []
        for affordance in self.affordances:
            if affordance.get("enabled") is not True or affordance.get("action_id") != action_id:
                continue
            locations = tuple(affordance.get("location_ids") or ())
            if locations and actor.location_id not in locations:
                continue
            objects = tuple(affordance.get("object_ids") or ())
            if target.object_id is not None and target.object_id not in objects:
                continue
            matches.append(affordance)
        return tuple(matches)

    def _evaluate(
        self,
        *,
        definition: Mapping[str, Any],
        affordance: Mapping[str, Any],
        actor: AtomicActorSnapshot,
        target: AtomicActionTarget,
        context: AtomicRuntimeContext,
    ) -> tuple[bool, str]:
        if actor.actor_type not in tuple(definition.get("actor_types") or ()):
            return False, "permission_denied"
        if not actor.available:
            return False, "actor_unavailable"
        if definition.get("preconditions", {}).get("requires_stage") and not context.stage_authorized:
            return False, "permission_denied"
        if target.location_id is not None and target.location_id != actor.location_id:
            return False, "route_unreachable"
        if not context.location_open:
            return False, "location_closed"
        if target.target_type not in tuple(definition.get("target_types") or ()):
            return False, "target_unavailable"
        if target.object_id is not None and target.object_id not in context.known_object_ids:
            return False, "target_unavailable"
        if target.target_type == "resident" and target.agent_id not in context.known_resident_ids:
            return False, "target_unavailable"
        if target.target_type == "participant" and not context.participant_present:
            return False, "target_unavailable"
        required_permissions = set(definition.get("permission_keys") or ()) | set(
            affordance.get("permission_keys") or ()
        )
        if not required_permissions <= actor.permissions:
            return False, "permission_denied"
        required_capabilities = set(definition.get("capability_keys") or ()) | set(
            affordance.get("capability_keys") or ()
        )
        if not required_capabilities <= actor.capabilities:
            return False, "capability_missing"
        minimum = int(definition.get("min_participants", 1))
        maximum = int(definition.get("max_participants", 20))
        if not minimum <= context.participant_count <= maximum:
            return False, "participant_bounds_unsatisfied"
        conditions = {
            **dict(definition.get("preconditions") or {}),
            **dict(affordance.get("conditions") or {}),
        }
        if conditions.get("location_open") is True and not context.location_open:
            return False, "location_closed"
        expected_actor_state = conditions.get("actor_state_equals") or {}
        if not _contains_state(actor.state, expected_actor_state):
            return False, "actor_unavailable"
        expected_object_state = conditions.get("object_state_equals") or {}
        actual_object_state = (
            context.object_states.get(target.object_id, {})
            if target.object_id is not None
            else {}
        )
        if not _contains_state(actual_object_state, expected_object_state):
            return False, "target_unavailable"
        return True, "authorized"

    def resolve_candidates(
        self,
        *,
        actor: AtomicActorSnapshot,
        context: AtomicRuntimeContext,
        include_blocked: bool = False,
    ) -> tuple[AtomicActionCandidate, ...]:
        candidates: list[AtomicActionCandidate] = []
        for affordance in sorted(
            self.affordances,
            key=lambda item: str(item.get("affordance_id", "")),
        ):
            if affordance.get("enabled") is not True:
                continue
            action_id = str(affordance.get("action_id") or "")
            definition = self.actions.get(action_id)
            if definition is None:
                continue
            objects = tuple(affordance.get("object_ids") or ())
            if objects:
                targets = tuple(
                    AtomicActionTarget(
                        location_id=actor.location_id,
                        object_id=str(object_id),
                    )
                    for object_id in objects
                )
            else:
                target_types = tuple(definition.get("target_types") or ())
                targets_list: list[AtomicActionTarget] = []
                if "location" in target_types:
                    targets_list.append(
                        AtomicActionTarget(location_id=actor.location_id)
                    )
                if "participant" in target_types and context.participant_present:
                    targets_list.append(
                        AtomicActionTarget(
                            location_id=actor.location_id,
                            actor_type="participant",
                        )
                    )
                if "resident" in target_types:
                    targets_list.extend(
                        AtomicActionTarget(
                            location_id=actor.location_id,
                            agent_id=agent_id,
                            actor_type="resident",
                        )
                        for agent_id in sorted(context.known_resident_ids)
                    )
                if "none" in target_types:
                    targets_list.append(AtomicActionTarget())
                targets = tuple(targets_list)
            for target in targets:
                available, reason_code = self._evaluate(
                    definition=definition,
                    affordance=affordance,
                    actor=actor,
                    target=target,
                    context=context,
                )
                if available or include_blocked:
                    candidates.append(
                        AtomicActionCandidate(
                            action_id=action_id,
                            affordance_id=str(affordance.get("affordance_id") or ""),
                            label=dict(definition.get("label") or {}),
                            execution_mode=str(definition.get("execution_mode") or "execute"),
                            target=target,
                            duration_minutes=int(definition.get("duration_minutes", 0)),
                            input_definitions=tuple(
                                dict(item) for item in definition.get("inputs", ())
                            ),
                            available=available,
                            reason_code=reason_code,
                        )
                    )
        return tuple(candidates)

    def _validate_inputs(
        self,
        definition: Mapping[str, Any],
        values: Mapping[str, Any],
    ) -> dict[str, Any]:
        definitions = {
            str(item.get("input_id")): dict(item)
            for item in definition.get("inputs", ())
        }
        unknown = sorted(set(values) - set(definitions))
        if unknown:
            raise _reason(
                "Atomic action contains an unknown input: " + ", ".join(unknown),
                "unknown_reference",
            )
        missing = sorted(
            input_id
            for input_id, item in definitions.items()
            if item.get("required") is True and input_id not in values
        )
        if missing:
            raise _reason(
                "Atomic action is missing required input: " + ", ".join(missing),
                "unknown_reference",
            )
        normalized: dict[str, Any] = {}
        for input_id, value in values.items():
            item = definitions[input_id]
            value_type = item.get("value_type")
            if value_type == "boolean":
                valid = isinstance(value, bool)
            elif value_type == "integer":
                valid = isinstance(value, int) and not isinstance(value, bool)
                if valid and item.get("minimum") is not None:
                    valid = value >= int(item["minimum"])
                if valid and item.get("maximum") is not None:
                    valid = value <= int(item["maximum"])
            elif value_type == "identifier":
                valid = isinstance(value, str) and bool(value.strip())
                allowed_values = tuple(item.get("allowed_values") or ())
                if valid and allowed_values:
                    valid = value in allowed_values
            elif value_type in ("free_text", "object_command"):
                valid = (
                    isinstance(value, str)
                    and bool(value.strip())
                    and len(value) <= int(item.get("max_length", 0))
                )
            else:
                valid = False
            if not valid:
                raise _reason(
                    f"Atomic action input {input_id!r} is invalid.",
                    "unknown_reference",
                )
            normalized[input_id] = value.strip() if isinstance(value, str) else value
        return normalized

    def prepare(
        self,
        *,
        action_id: str,
        actor: AtomicActorSnapshot,
        target: AtomicActionTarget,
        context: AtomicRuntimeContext,
        inputs: Mapping[str, Any],
    ) -> PreparedAtomicAction:
        definition = self._definition(action_id)
        matches = self._matching_affordances(
            action_id=action_id,
            actor=actor,
            target=target,
        )
        if not matches:
            raise _reason(
                "The action is not afforded at the actor location or target.",
                "target_unavailable",
            )
        rejection: str | None = None
        selected: Mapping[str, Any] | None = None
        for affordance in matches:
            available, reason_code = self._evaluate(
                definition=definition,
                affordance=affordance,
                actor=actor,
                target=target,
                context=context,
            )
            if available:
                selected = affordance
                break
            rejection = rejection or reason_code
        if selected is None:
            raise _reason("Atomic action is not currently authorized.", rejection or "target_unavailable")
        normalized_inputs = self._validate_inputs(definition, inputs)
        effect_allowlist = set(definition.get("effect_allowlist") or ())
        effects = tuple(dict(item) for item in definition.get("consequences", ()))
        for effect in effects:
            effect_type = str(effect.get("effect_type") or "")
            if effect_type not in ATOMIC_EFFECT_TYPES or effect_type not in effect_allowlist:
                raise _reason(
                    "Atomic action contains an illegal effect.",
                    "unknown_reference",
                )
            if effect_type == "set_object_state" and target.object_id is None:
                raise _reason(
                    "Object-state effect requires an object target.",
                    "target_unavailable",
                )
        execution_mode = str(definition.get("execution_mode") or "execute")
        if execution_mode == "proposal" and effects:
            raise _reason(
                "Proposal actions cannot mutate world state.",
                "permission_denied",
            )
        return PreparedAtomicAction(
            runtime_version=self.runtime_version,
            action_id=action_id,
            affordance_id=str(selected.get("affordance_id") or ""),
            execution_mode=execution_mode,
            duration_minutes=int(definition.get("duration_minutes", 0)),
            target=target,
            normalized_inputs=normalized_inputs,
            effects=effects,
            interruptible=bool(definition.get("interruptible", True)),
        )
