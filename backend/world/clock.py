"""Pure virtual-clock operations for clamp and multi-day worlds."""

from dataclasses import dataclass

from world.specs import CalendarSpec


@dataclass(frozen=True, order=True)
class ClockPosition:
    day: int
    minute: int


@dataclass(frozen=True)
class ClockAdvance:
    before: ClockPosition
    after: ClockPosition
    crossed_days: int
    reached_world_end: bool


def _validate_position(calendar: CalendarSpec, position: ClockPosition) -> None:
    if not 1 <= position.day <= calendar.total_days:
        raise ValueError(
            f"Clock day must be between 1 and {calendar.total_days}."
        )
    if not calendar.day_start_minute <= position.minute <= calendar.day_end_minute:
        raise ValueError(
            "Clock minute must be within the world's playable day interval."
        )


def advance_clock(
    calendar: CalendarSpec,
    current_day: int,
    current_minute: int,
    minutes: int,
) -> ClockAdvance:
    """Advance a virtual clock according to its explicit rollover policy."""

    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 0:
        raise ValueError("minutes must be a non-negative integer.")

    before = ClockPosition(current_day, current_minute)
    _validate_position(calendar, before)

    if calendar.rollover == "clamp":
        after = ClockPosition(
            current_day,
            min(calendar.day_end_minute, current_minute + minutes),
        )
        return ClockAdvance(
            before=before,
            after=after,
            crossed_days=0,
            reached_world_end=(
                after.day == calendar.total_days
                and after.minute == calendar.day_end_minute
            ),
        )

    day = current_day
    minute = current_minute
    remaining = minutes
    crossed_days = 0

    while remaining > 0:
        available_today = calendar.day_end_minute - minute
        if remaining <= available_today:
            minute += remaining
            remaining = 0
            break

        remaining -= available_today
        if day >= calendar.total_days:
            minute = calendar.day_end_minute
            remaining = 0
            break

        day += 1
        crossed_days += 1
        minute = calendar.day_start_minute

    after = ClockPosition(day, minute)
    return ClockAdvance(
        before=before,
        after=after,
        crossed_days=crossed_days,
        reached_world_end=(
            after.day == calendar.total_days
            and after.minute == calendar.day_end_minute
        ),
    )


def advance_to_next_day(
    calendar: CalendarSpec,
    current_day: int,
    current_minute: int,
) -> ClockAdvance:
    """Jump to the next playable day start, or the final world end."""

    before = ClockPosition(current_day, current_minute)
    _validate_position(calendar, before)

    if current_day < calendar.total_days:
        after = ClockPosition(current_day + 1, calendar.day_start_minute)
        crossed_days = 1
    else:
        after = ClockPosition(current_day, calendar.day_end_minute)
        crossed_days = 0

    return ClockAdvance(
        before=before,
        after=after,
        crossed_days=crossed_days,
        reached_world_end=(
            after.day == calendar.total_days
            and after.minute == calendar.day_end_minute
        ),
    )


def is_due(
    due_day: int,
    due_minute: int,
    current_day: int,
    current_minute: int,
) -> bool:
    """Return whether a day/minute deadline has been reached."""

    return ClockPosition(due_day, due_minute) <= ClockPosition(
        current_day, current_minute
    )
