# SPDX-FileCopyrightText: 2026 GARDENA GmbH
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for turning schedules between device bytes and readable entries."""

from __future__ import annotations

import pytest

from custom_components.gardena_smart_local_preview.schedules import (
    build_schedule,
    describe_schedule,
)

# Read off a smart SILENO city/life (with LONA): one entry, Monday to
# Saturday, starting 09:30, running 340 minutes.
REAL_SCHEDULE = bytes.fromhex("007e091e540100")


def test_describes_a_schedule_read_from_a_mower() -> None:
    """The blob a real mower reported reads back as what its app shows."""
    assert describe_schedule(REAL_SCHEDULE) == [
        {
            "days": [
                "monday",
                "tuesday",
                "wednesday",
                "thursday",
                "friday",
                "saturday",
            ],
            "start": "09:30",
            "duration_minutes": 340,
        }
    ]


def test_round_trips_a_real_schedule() -> None:
    """Building what was described gives the device's own bytes back.

    A schedule is written as a whole, so anything lost in the description
    would be written back as a changed schedule.
    """
    assert build_schedule(describe_schedule(REAL_SCHEDULE)) == REAL_SCHEDULE


def test_builds_several_entries() -> None:
    """Each entry gets its own slot, numbered in the order given."""
    config = build_schedule(
        [
            {"days": ["monday"], "start": "07:00", "duration_minutes": 60},
            {"days": ["sunday"], "start": "18:15", "duration_minutes": 90},
        ]
    )

    assert len(config) == 14
    assert describe_schedule(config)[1] == {
        "days": ["sunday"],
        "start": "18:15",
        "duration_minutes": 90,
    }


@pytest.mark.parametrize(
    "entry",
    [
        {"days": [], "start": "09:00", "duration_minutes": 60},
        {"days": ["someday"], "start": "09:00", "duration_minutes": 60},
        {"days": ["monday"], "start": "25:00", "duration_minutes": 60},
        {"days": ["monday"], "start": "09:70", "duration_minutes": 60},
        {"days": ["monday"], "start": "09:00", "duration_minutes": 0},
        {"days": ["monday"], "start": "09:00", "duration_minutes": 100000},
    ],
)
def test_refuses_what_a_device_would_not_accept(entry: dict) -> None:
    """A bad schedule is refused here rather than written to a mower."""
    with pytest.raises(ValueError):
        build_schedule([entry])


def test_refuses_more_schedules_than_a_device_holds() -> None:
    """Fifteen entries would silently lose one."""
    entry = {"days": ["monday"], "start": "09:00", "duration_minutes": 60}

    with pytest.raises(ValueError):
        build_schedule([entry] * 15)


# Read off the same mower later the same day, after its schedule had been
# changed from the official app: five weekdays, 10:30, three hours — and a
# different first byte.
CHANGED_SCHEDULE = bytes.fromhex("80760a1eb40000")


def test_round_trips_a_schedule_whose_first_byte_is_set() -> None:
    """The byte the device keeps per entry is written back, not guessed."""
    described = describe_schedule(CHANGED_SCHEDULE)

    assert described == [
        {
            "days": ["monday", "tuesday", "thursday", "friday", "saturday"],
            "start": "10:30",
            "duration_minutes": 180,
        }
    ]
    assert build_schedule(described, template=CHANGED_SCHEDULE) == CHANGED_SCHEDULE


def test_a_new_entry_inherits_the_devices_own_byte() -> None:
    """An added slot copies what the device uses rather than inventing one."""
    config = build_schedule(
        [
            {"days": ["monday"], "start": "10:30", "duration_minutes": 180},
            {"days": ["sunday"], "start": "12:00", "duration_minutes": 60},
        ],
        template=CHANGED_SCHEDULE,
    )

    assert config[0] == 0x80
    assert config[7] == 0x80


def test_without_a_template_the_byte_is_zero() -> None:
    """With nothing to carry over, an entry is written with a plain zero."""
    config = build_schedule(describe_schedule(REAL_SCHEDULE))

    assert config[0] == 0x00
    assert config == REAL_SCHEDULE
