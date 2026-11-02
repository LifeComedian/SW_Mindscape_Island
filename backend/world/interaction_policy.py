"""Opt-in interaction rules for versioned worlds."""
from dataclasses import dataclass
from collections.abc import Mapping
from world.specs import WorldSpecValidationError


@dataclass(frozen=True)
class InteractionPolicy:
    policy_version: str = "session-interaction-v1"
    enabled: bool = True
    ambient_enabled: bool = False
    conversation_minutes: int = 10
    short_conversation_minutes: int = 5
    focus_lease_seconds: int = 300
    max_contacts_per_day: int = 2
    contact_cooldown_minutes: int = 60
    max_pending_contacts: int = 1

    @classmethod
    def parse(cls, value):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise WorldSpecValidationError("Invalid interaction policy fields.")
        if value["policy_version"] != cls().policy_version:
            raise WorldSpecValidationError("Unknown interaction policy version.")
        if type(value["enabled"]) is not bool or value["ambient_enabled"] is not False:
            raise WorldSpecValidationError("M8 does not support ambient conversations.")
        for key, bounds in {"conversation_minutes": (10, 10), "short_conversation_minutes": (5, 5),
                            "focus_lease_seconds": (120, 1800), "max_contacts_per_day": (0, 4),
                            "contact_cooldown_minutes": (30, 240), "max_pending_contacts": (1, 1)}.items():
            if type(value[key]) is not int or not bounds[0] <= value[key] <= bounds[1]:
                raise WorldSpecValidationError(f"Invalid interaction limit: {key}.")
        return cls(**dict(value))


def interaction_policy(spec):
    value = spec.systems.get("interaction_policy")
    policy = InteractionPolicy.parse(value) if value is not None else None
    return policy if policy and policy.enabled else None
