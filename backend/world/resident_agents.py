"""Resident perception snapshots, intents, and decision policies."""

from dataclasses import dataclass
from typing import Protocol, Sequence, runtime_checkable


class ResidentDecisionError(ValueError):
    """Raised when a policy cannot make an auditable decision."""


@dataclass(frozen=True)
class ScheduleDirective:
    """The resident's resolved schedule target at the snapshot time."""

    state_id: str
    location_id: str
    activity: str
    goal: str

    def __post_init__(self) -> None:
        if not self.state_id:
            raise ResidentDecisionError("schedule state_id cannot be empty.")
        if not self.location_id:
            raise ResidentDecisionError("schedule location_id cannot be empty.")
        if not self.activity:
            raise ResidentDecisionError("schedule activity cannot be empty.")
        if not self.goal:
            raise ResidentDecisionError("schedule goal cannot be empty.")


@dataclass(frozen=True)
class ResidentPerception:
    """A minimal immutable snapshot of facts visible to one resident."""

    world_version: str
    resident_id: int
    day: int
    minute: int
    current_location_id: str
    current_schedule_state_id: str
    current_activity: str
    current_goal: str
    schedule: ScheduleDirective
    participant_present: bool = False
    visible_resident_ids: tuple[int, ...] = ()
    visible_object_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.world_version:
            raise ResidentDecisionError("world_version cannot be empty.")
        if isinstance(self.resident_id, bool) or self.resident_id < 1:
            raise ResidentDecisionError("resident_id must be positive.")
        if isinstance(self.day, bool) or self.day < 1:
            raise ResidentDecisionError("day must be positive.")
        if isinstance(self.minute, bool) or not 0 <= self.minute <= 1439:
            raise ResidentDecisionError("minute must be between 0 and 1439.")
        if not self.current_location_id:
            raise ResidentDecisionError("current_location_id cannot be empty.")
        if not self.current_schedule_state_id:
            raise ResidentDecisionError(
                "current_schedule_state_id cannot be empty."
            )
        if any(
            isinstance(agent_id, bool) or agent_id < 1
            for agent_id in self.visible_resident_ids
        ):
            raise ResidentDecisionError(
                "visible_resident_ids must contain positive resident ids."
            )
        if any(not object_id for object_id in self.visible_object_ids):
            raise ResidentDecisionError(
                "visible_object_ids cannot contain empty values."
            )
        object.__setattr__(
            self,
            "visible_resident_ids",
            tuple(self.visible_resident_ids),
        )
        object.__setattr__(
            self,
            "visible_object_ids",
            tuple(self.visible_object_ids),
        )


@dataclass(frozen=True)
class CandidateIntent:
    """A proposed resident intent that still requires world validation."""

    intent_id: str
    intent_type: str
    priority: int
    proposed_by: str
    schedule_state_id: str | None = None
    target_location_id: str | None = None
    target_resident_id: int | None = None
    target_object_id: str | None = None
    weight: int = 1
    reason_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.intent_id:
            raise ResidentDecisionError("intent_id cannot be empty.")
        if not self.intent_type:
            raise ResidentDecisionError("intent_type cannot be empty.")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise ResidentDecisionError("intent priority must be an integer.")
        if not self.proposed_by:
            raise ResidentDecisionError("proposed_by cannot be empty.")
        if self.target_resident_id is not None and (
            isinstance(self.target_resident_id, bool)
            or self.target_resident_id < 1
        ):
            raise ResidentDecisionError(
                "target_resident_id must be positive when provided."
            )
        if isinstance(self.weight, bool) or not isinstance(self.weight, int) or self.weight < 0:
            raise ResidentDecisionError("intent weight must be a non-negative integer.")
        if any(not tag for tag in self.reason_tags):
            raise ResidentDecisionError("intent reason_tags cannot contain empty values.")
        object.__setattr__(self, "reason_tags", tuple(self.reason_tags))


@dataclass(frozen=True)
class ResidentDecision:
    """An auditable policy result without hidden reasoning text."""

    selected_intent: CandidateIntent
    considered_intent_ids: tuple[str, ...]
    policy_id: str
    policy_version: str
    reason_code: str
    deterministic: bool

    def __post_init__(self) -> None:
        if self.selected_intent.intent_id not in self.considered_intent_ids:
            raise ResidentDecisionError(
                "selected_intent must be included in considered_intent_ids."
            )
        if not self.policy_id or not self.policy_version:
            raise ResidentDecisionError(
                "policy_id and policy_version cannot be empty."
            )
        if not self.reason_code:
            raise ResidentDecisionError("reason_code cannot be empty.")


@runtime_checkable
class ResidentDecisionPolicy(Protocol):
    """Async extension point for deterministic rules or future LLM policies."""

    policy_id: str
    policy_version: str

    async def decide(
        self,
        perception: ResidentPerception,
        candidates: Sequence[CandidateIntent],
    ) -> ResidentDecision:
        """Select one candidate without applying it to world state."""
        ...


def validate_resident_decision(
    decision: ResidentDecision,
    candidates: Sequence[CandidateIntent],
) -> CandidateIntent:
    """Return the authoritative candidate or reject a forged policy payload."""

    candidate_rows = tuple(candidates)
    intent_ids = tuple(candidate.intent_id for candidate in candidate_rows)
    if len(set(intent_ids)) != len(intent_ids):
        raise ResidentDecisionError("Candidate intent ids must be unique.")
    if decision.considered_intent_ids != intent_ids:
        raise ResidentDecisionError(
            "Decision considered_intent_ids must match the candidate set."
        )
    authoritative = next(
        (
            candidate
            for candidate in candidate_rows
            if candidate.intent_id == decision.selected_intent.intent_id
        ),
        None,
    )
    if authoritative is None or authoritative != decision.selected_intent:
        raise ResidentDecisionError(
            "Selected intent payload must exactly match an authoritative candidate."
        )
    return authoritative


def schedule_driven_candidates(
    perception: ResidentPerception,
) -> tuple[CandidateIntent, ...]:
    """Propose a scheduled action plus a deterministic no-op fallback."""

    state_id = perception.schedule.state_id
    if perception.current_location_id != perception.schedule.location_id:
        scheduled = CandidateIntent(
            intent_id=f"schedule:{state_id}:relocate",
            intent_type="relocate",
            priority=100,
            proposed_by="schedule",
            schedule_state_id=state_id,
            target_location_id=perception.schedule.location_id,
        )
    else:
        scheduled = CandidateIntent(
            intent_id=f"schedule:{state_id}:continue",
            intent_type="continue_schedule",
            priority=100,
            proposed_by="schedule",
            schedule_state_id=state_id,
            target_location_id=perception.current_location_id,
        )

    fallback = CandidateIntent(
        intent_id=f"schedule:{state_id}:wait",
        intent_type="wait",
        priority=0,
        proposed_by="schedule",
        schedule_state_id=state_id,
        target_location_id=perception.current_location_id,
    )
    return scheduled, fallback


class ScheduleDrivenPolicy:
    """Deterministically prefer the candidate aligned with the current schedule."""

    policy_id = "schedule-driven"
    policy_version = "v1"

    @staticmethod
    def _alignment(
        perception: ResidentPerception,
        candidate: CandidateIntent,
    ) -> int:
        if candidate.schedule_state_id != perception.schedule.state_id:
            return 0

        needs_relocation = (
            perception.current_location_id != perception.schedule.location_id
        )
        if (
            needs_relocation
            and candidate.intent_type == "relocate"
            and candidate.target_location_id == perception.schedule.location_id
        ):
            return 3
        if (
            not needs_relocation
            and candidate.intent_type == "continue_schedule"
            and candidate.target_location_id == perception.current_location_id
        ):
            return 3
        if candidate.intent_type == "wait":
            return 1
        return 2

    def decide_now(
        self,
        perception: ResidentPerception,
        candidates: Sequence[CandidateIntent],
    ) -> ResidentDecision:
        """Synchronously select a schedule-aligned candidate without I/O."""

        candidate_rows = tuple(candidates)
        if not candidate_rows:
            raise ResidentDecisionError("At least one candidate intent is required.")

        intent_ids = tuple(candidate.intent_id for candidate in candidate_rows)
        if len(set(intent_ids)) != len(intent_ids):
            raise ResidentDecisionError("Candidate intent ids must be unique.")

        selected = min(
            candidate_rows,
            key=lambda candidate: (
                -self._alignment(perception, candidate),
                -candidate.priority,
                candidate.intent_id,
            ),
        )
        if (
            selected.intent_type == "relocate"
            and selected.target_location_id == perception.schedule.location_id
        ):
            reason_code = "scheduled_relocation"
        elif selected.intent_type == "continue_schedule":
            reason_code = "scheduled_activity"
        elif selected.intent_type == "wait":
            reason_code = "schedule_wait_fallback"
        else:
            reason_code = "highest_ranked_candidate"

        decision = ResidentDecision(
            selected_intent=selected,
            considered_intent_ids=intent_ids,
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            reason_code=reason_code,
            deterministic=True,
        )
        validate_resident_decision(decision, candidate_rows)
        return decision

    async def decide(
        self,
        perception: ResidentPerception,
        candidates: Sequence[CandidateIntent],
    ) -> ResidentDecision:
        return self.decide_now(perception, candidates)
