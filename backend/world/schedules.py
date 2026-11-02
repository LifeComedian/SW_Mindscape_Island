"""Pure resident-schedule resolution with optional per-day overrides."""

from world.clock import ClockPosition
from world.specs import ResidentSpec, ScheduleBlock, WorldSpec, WorldSpecValidationError


class ScheduleResolutionError(LookupError):
    """Raised when no unambiguous resident schedule applies."""


def _matching_blocks(
    resident: ResidentSpec,
    day: int,
    minute: int,
) -> tuple[list[ScheduleBlock], list[ScheduleBlock]]:
    recurring: list[ScheduleBlock] = []
    day_specific: list[ScheduleBlock] = []
    for block in resident.schedule:
        if not block.start_minute <= minute <= block.end_minute:
            continue
        if block.days is None:
            recurring.append(block)
        elif day in block.days:
            day_specific.append(block)
    return recurring, day_specific


def resolve_resident_schedule(
    spec: WorldSpec,
    agent_id: int,
    day: int,
    minute: int,
) -> ScheduleBlock:
    if agent_id not in spec.residents:
        raise ScheduleResolutionError(f"Unknown resident agent_id: {agent_id}.")
    if not 1 <= day <= spec.calendar.total_days:
        raise ScheduleResolutionError(
            f"Day must be between 1 and {spec.calendar.total_days}."
        )
    if not 0 <= minute <= 1439:
        raise ScheduleResolutionError("Schedule minute must be between 0 and 1439.")

    resident = spec.residents[agent_id]
    recurring, day_specific = _matching_blocks(resident, day, minute)
    applicable = day_specific or recurring
    if not applicable:
        raise ScheduleResolutionError(
            f"No schedule entry for agent {agent_id} on day {day} at {minute}."
        )
    if len(applicable) > 1:
        states = ", ".join(sorted(block.state_id for block in applicable))
        raise ScheduleResolutionError(
            f"Ambiguous schedule for agent {agent_id} on day {day} at "
            f"{minute}: {states}."
        )
    return applicable[0]


def schedule_transition_points(
    spec: WorldSpec,
    start_day: int,
    start_minute: int,
    end_day: int,
    end_minute: int,
) -> tuple[ClockPosition, ...]:
    """Return every possible schedule boundary in ``(start, end]``.

    The result includes day starts and both sides of day-specific overrides.
    A runtime can process these sparse points instead of simulating each minute,
    while still observing a resident who leaves and later returns before the
    final clock position.
    """

    calendar = spec.calendar
    start = ClockPosition(start_day, start_minute)
    end = ClockPosition(end_day, end_minute)
    for label, position in (("start", start), ("end", end)):
        if not 1 <= position.day <= calendar.total_days:
            raise ScheduleResolutionError(
                f"{label} day must be between 1 and {calendar.total_days}."
            )
        if not calendar.day_start_minute <= position.minute <= calendar.day_end_minute:
            raise ScheduleResolutionError(
                f"{label} minute must be inside the playable day interval."
            )
    if end < start:
        raise ScheduleResolutionError("Schedule interval end cannot precede start.")

    candidates: set[ClockPosition] = set()
    for day in range(start.day, end.day + 1):
        candidates.add(ClockPosition(day, calendar.day_start_minute))
        for resident in spec.residents.values():
            for block in resident.schedule:
                if block.days is not None and day not in block.days:
                    continue
                for minute in (block.start_minute, block.end_minute + 1):
                    if calendar.day_start_minute <= minute <= calendar.day_end_minute:
                        candidates.add(ClockPosition(day, minute))

    return tuple(sorted(point for point in candidates if start < point <= end))


def validate_resident_schedules(spec: WorldSpec) -> None:
    for resident_key, resident in spec.residents.items():
        if resident_key != resident.agent_id:
            raise WorldSpecValidationError(
                f"Resident key {resident_key} does not match agent_id "
                f"{resident.agent_id}."
            )

        state_ids = [block.state_id for block in resident.schedule]
        if len(set(state_ids)) != len(state_ids):
            raise WorldSpecValidationError(
                f"Resident {resident.agent_id} has duplicate schedule state ids."
            )

        for block in resident.schedule:
            if block.location_id not in spec.locations:
                raise WorldSpecValidationError(
                    f"Resident {resident.agent_id} schedule {block.state_id!r} "
                    f"references missing location {block.location_id!r}."
                )
            if block.days is not None and any(
                day > spec.calendar.total_days for day in block.days
            ):
                raise WorldSpecValidationError(
                    f"Resident {resident.agent_id} schedule {block.state_id!r} "
                    "references a day outside the world calendar."
                )

        for day in range(1, spec.calendar.total_days + 1):
            for minute in range(
                spec.calendar.day_start_minute,
                spec.calendar.day_end_minute + 1,
            ):
                try:
                    resolve_resident_schedule(
                        spec,
                        resident.agent_id,
                        day,
                        minute,
                    )
                except ScheduleResolutionError as exc:
                    raise WorldSpecValidationError(str(exc)) from exc
