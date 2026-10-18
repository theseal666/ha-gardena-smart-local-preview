# SPDX-FileCopyrightText: 2026 GARDENA GmbH
#
# SPDX-License-Identifier: Apache-2.0

"""Schedules, between the device's byte blob and something a person can read.

A Gen1 device keeps its schedule as a blob of seven-byte entries, which
gardena-smart-local-api parses and builds. What it cannot do is decide what a
schedule should look like in Home Assistant, which is what this module is
for: weekday names rather than a bit field, `HH:MM` rather than two integers,
and minutes as a plain number.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from gardena_smart_local_api.utils.schedules import (
    Gen1ScheduleEntry,
    Gen1Weekday,
    build_gen1_schedule_config,
    parse_gen1_schedule_config,
)

# The same order the lowercase names are offered and reported in
WEEKDAYS: dict[str, Gen1Weekday] = {
    "monday": Gen1Weekday.MONDAY,
    "tuesday": Gen1Weekday.TUESDAY,
    "wednesday": Gen1Weekday.WEDNESDAY,
    "thursday": Gen1Weekday.THURSDAY,
    "friday": Gen1Weekday.FRIDAY,
    "saturday": Gen1Weekday.SATURDAY,
    "sunday": Gen1Weekday.SUNDAY,
}

# "up to 14 schedules, 7 bytes each", per the model definitions
MAX_SCHEDULES = 14

# What a mower reports in "paused until" when nothing is paused: the device's
# own idle value, seen on a mower that had never been parked. Parking writes
# a date far in the future instead, so this is the way back.
NOT_PAUSED = (1970).to_bytes(2, "little") + bytes([1, 1, 0, 0])


def is_paused(raw: bytes | None) -> bool | None:
    """Return whether the mower is currently paused.

    The resource holds the local wall-clock time a pause runs until, as a
    year and then month, day, hour and minute. Docking writes a date far in
    the future and an idle mower reports one in 1970, but there is no need to
    recognise either: a pause that has not run out yet is a pause.
    """
    if not isinstance(raw, bytes) or len(raw) != 6:
        return None
    year = int.from_bytes(raw[0:2], "little")
    month, day, hour, minute = raw[2:6]
    try:
        until = datetime(year, month, day, hour, minute)
    except ValueError:
        return None
    return until > datetime.now()


def describe_schedule(raw: bytes) -> list[dict[str, Any]]:
    """Return the entries of a schedule blob in readable form."""
    described: list[dict[str, Any]] = []
    for entry in parse_gen1_schedule_config(raw):
        described.append(
            {
                "days": [
                    name for name, flag in WEEKDAYS.items() if entry.weekdays & flag
                ],
                "start": f"{entry.start_hour:02d}:{entry.start_minute:02d}",
                "duration_minutes": entry.duration_minutes,
            }
        )
    return described


def build_schedule(
    entries: list[dict[str, Any]], template: bytes | None = None
) -> bytes:
    """Build a schedule blob from entries given as days, start and duration.

    The first byte of an entry is carried over from `template`, the schedule
    the device currently holds. The dependency calls it a schedule id, but a
    mower was observed holding 0x80 in it for its only entry and 0x00 for an
    earlier one, so it behaves more like a flag whose meaning is not
    documented anywhere available. Writing a guess there could change
    something invisible, so what the device chose is written back: by slot,
    falling back to the first slot's value, and to zero for a device whose
    schedule was empty.

    Raises ValueError on anything the device would not accept, so a bad
    schedule is refused here rather than written to a mower.
    """
    if len(entries) > MAX_SCHEDULES:
        raise ValueError(f"A device holds at most {MAX_SCHEDULES} schedules")

    held = parse_gen1_schedule_config(template) if template else []
    fallback_id = held[0].schedule_id if held else 0

    built: list[Gen1ScheduleEntry] = []
    for index, entry in enumerate(entries):
        days = entry.get("days") or []
        unknown = [day for day in days if day not in WEEKDAYS]
        if unknown:
            raise ValueError(f"Unknown weekday(s): {', '.join(unknown)}")
        if not days:
            raise ValueError("A schedule needs at least one weekday")

        weekdays = Gen1Weekday(0)
        for day in days:
            weekdays |= WEEKDAYS[day]

        hour, _, minute = str(entry["start"]).partition(":")
        start_hour, start_minute = int(hour), int(minute)
        if not 0 <= start_hour <= 23 or not 0 <= start_minute <= 59:
            raise ValueError(f"Start time out of range: {entry['start']}")

        duration = int(entry["duration_minutes"])
        # Two bytes on the wire, and a schedule cannot outlast its own week
        if not 1 <= duration <= 60 * 24 * 7:
            raise ValueError(f"Duration out of range: {duration} minutes")

        built.append(
            Gen1ScheduleEntry(
                schedule_id=held[index].schedule_id
                if index < len(held)
                else fallback_id,
                weekdays=weekdays,
                start_hour=start_hour,
                start_minute=start_minute,
                duration_minutes=duration,
                # Every entry seen so far carries 0 here, on two mowers and
                # across a schedule change made from the official app.
                action=0,
            )
        )
    return build_gen1_schedule_config(built)


def entry_count(raw: bytes | None) -> int:
    """Return how many entries a schedule blob holds."""
    return len(parse_gen1_schedule_config(raw)) if raw else 0


def replace_entry(raw: bytes, index: int, **changes: Any) -> bytes:
    """Return the schedule with one entry's days, start or duration changed.

    The whole schedule is rebuilt because the device holds it as one blob,
    and every other entry is passed back exactly as it was read.
    """
    entries = describe_schedule(raw)
    if not 0 <= index < len(entries):
        raise ValueError(f"No schedule in slot {index}")
    entries[index] = {**entries[index], **changes}
    return build_schedule(entries, template=raw)


def add_entry(raw: bytes | None, entry: dict[str, Any]) -> bytes:
    """Return the schedule with one more entry appended."""
    entries = describe_schedule(raw) if raw else []
    return build_schedule([*entries, entry], template=raw)


def remove_entry(raw: bytes, index: int) -> bytes:
    """Return the schedule without the entry in the given slot.

    Refuses to remove the last one. A mower does not hold an empty schedule:
    measured twice on a Gen1 mower, an empty one was written, acknowledged,
    and three seconds later the mower reported a schedule of its own —
    every day, from 00:00, for 1440 minutes. Emptying the schedule therefore
    means "mow at any hour", which is the opposite of what removing the last
    entry looks like it does, and it is how that mower came to set off at
    02:40 in the morning.
    """
    entries = describe_schedule(raw)
    if not 0 <= index < len(entries):
        raise ValueError(f"No schedule in slot {index}")
    if len(entries) == 1:
        raise ValueError(
            "A device replaces an empty schedule with one of its own, every "
            "day around the clock. Turn the schedule off with the run "
            "schedule switch instead of removing the last entry"
        )
    remaining = [e for position, e in enumerate(entries) if position != index]
    return build_schedule(remaining, template=raw)


def set_day(raw: bytes, index: int, day: str, enabled: bool) -> bytes:
    """Return the schedule with one weekday turned on or off for one entry."""
    entries = describe_schedule(raw)
    if not 0 <= index < len(entries):
        raise ValueError(f"No schedule in slot {index}")
    days = set(entries[index]["days"])
    if enabled:
        days.add(day)
    else:
        days.discard(day)
    if not days:
        raise ValueError("A schedule needs at least one weekday")
    # Reported in week order rather than in the order they were toggled
    ordered = [name for name in WEEKDAYS if name in days]
    return replace_entry(raw, index, days=ordered)
