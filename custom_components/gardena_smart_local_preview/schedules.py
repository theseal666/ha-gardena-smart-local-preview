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


def build_schedule(entries: list[dict[str, Any]]) -> bytes:
    """Build a schedule blob from entries given as days, start and duration.

    Raises ValueError on anything the device would not accept, so a bad
    schedule is refused here rather than written to a mower.
    """
    if len(entries) > MAX_SCHEDULES:
        raise ValueError(f"A device holds at most {MAX_SCHEDULES} schedules")

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
                schedule_id=index,
                weekdays=weekdays,
                start_hour=start_hour,
                start_minute=start_minute,
                duration_minutes=duration,
                # The mowers seen so far carry 0 here; the resource is a
                # single schedule list, so there is no second action to pick.
                action=0,
            )
        )
    return build_gen1_schedule_config(built)
