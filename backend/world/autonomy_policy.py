"""Explicit shared-clock autonomy. Older packs do not opt in implicitly."""
from dataclasses import dataclass
from collections.abc import Mapping
from world.specs import WorldSpecValidationError


@dataclass(frozen=True)
class AutonomyPolicy:
    policy_version: str = "shared-clock-autonomy-v1"
    enabled: bool = False
    max_pending: int = 2
    dispatch_per_pulse: int = 2
    cooldown_minutes: int = 15
    read_posts_per_step: int = 2

    @classmethod
    def parse(cls, value):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise WorldSpecValidationError("Invalid autonomy policy fields.")
        if value["policy_version"] != cls().policy_version or type(value["enabled"]) is not bool:
            raise WorldSpecValidationError("Invalid autonomy policy version or enable flag.")
        for key, bounds in {"max_pending": (1, 2), "dispatch_per_pulse": (1, 2),
                            "cooldown_minutes": (5, 120), "read_posts_per_step": (1, 4)}.items():
            if type(value[key]) is not int or not bounds[0] <= value[key] <= bounds[1]:
                raise WorldSpecValidationError(f"Invalid autonomy limit: {key}.")
        return cls(**dict(value))


def autonomy_policy(spec):
    value = spec.systems.get("autonomy_policy")
    policy = AutonomyPolicy.parse(value) if value is not None else None
    return policy if policy and policy.enabled else None
