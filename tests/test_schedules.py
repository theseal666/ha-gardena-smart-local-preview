# SPDX-FileCopyrightText: 2026 GARDENA GmbH
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for turning schedules between device bytes and readable entries."""

from __future__ import annotations

import pytest

from custom_components.gardena_smart_local_preview.schedules import (
    add_entry,
    build_schedule,
    describe_schedule,
    remove_entry,
    replace_entry,
    set_day,
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


def test_replaces_one_entry_and_leaves_the_rest() -> None:
    """Editing a start time rewrites the blob without touching the others."""
    two = build_schedule(
        [
            {"days": ["monday"], "start": "07:00", "duration_minutes": 60},
            {"days": ["sunday"], "start": "18:15", "duration_minutes": 90},
        ]
    )

    edited = replace_entry(two, 0, start="08:45")

    assert describe_schedule(edited) == [
        {"days": ["monday"], "start": "08:45", "duration_minutes": 60},
        {"days": ["sunday"], "start": "18:15", "duration_minutes": 90},
    ]


def test_editing_keeps_the_devices_own_byte() -> None:
    """An edit must not drop the flag the device holds in each entry."""
    edited = replace_entry(CHANGED_SCHEDULE, 0, duration_minutes=240)

    assert edited[0] == 0x80
    assert describe_schedule(edited)[0]["duration_minutes"] == 240


def test_adds_to_what_the_device_already_holds() -> None:
    """Adding appends rather than replacing."""
    added = add_entry(
        CHANGED_SCHEDULE, {"days": ["sunday"], "start": "12:00", "duration_minutes": 60}
    )

    described = describe_schedule(added)
    assert len(described) == 2
    assert described[0]["start"] == "10:30"
    assert described[1]["days"] == ["sunday"]


def test_adds_to_an_empty_schedule() -> None:
    """A device with no schedule can be given its first one."""
    added = add_entry(
        None, {"days": ["monday"], "start": "09:00", "duration_minutes": 60}
    )

    assert describe_schedule(added) == [
        {"days": ["monday"], "start": "09:00", "duration_minutes": 60}
    ]


def test_removes_one_entry() -> None:
    """Removing a slot leaves the others in order."""
    two = add_entry(
        CHANGED_SCHEDULE, {"days": ["sunday"], "start": "12:00", "duration_minutes": 60}
    )

    assert describe_schedule(remove_entry(two, 0)) == [
        {"days": ["sunday"], "start": "12:00", "duration_minutes": 60}
    ]


def test_removing_the_last_entry_empties_the_schedule() -> None:
    """An empty schedule is an empty blob, as a device with none reports."""
    assert remove_entry(CHANGED_SCHEDULE, 0) == b""


@pytest.mark.parametrize("index", [-1, 1, 99])
def test_editing_a_slot_that_does_not_exist_is_refused(index: int) -> None:
    """A slot number from a stale dashboard does not rewrite slot zero."""
    with pytest.raises(ValueError):
        replace_entry(CHANGED_SCHEDULE, index, duration_minutes=60)
    with pytest.raises(ValueError):
        remove_entry(CHANGED_SCHEDULE, index)


def test_toggles_a_single_weekday() -> None:
    """Turning a day on leaves the rest of the entry alone."""
    with_sunday = set_day(CHANGED_SCHEDULE, 0, "sunday", True)

    assert describe_schedule(with_sunday) == [
        {
            "days": [
                "monday",
                "tuesday",
                "thursday",
                "friday",
                "saturday",
                "sunday",
            ],
            "start": "10:30",
            "duration_minutes": 180,
        }
    ]


def test_turning_a_day_off_keeps_week_order() -> None:
    """Days come back in week order however they were toggled."""
    without_thursday = set_day(CHANGED_SCHEDULE, 0, "thursday", False)

    assert describe_schedule(without_thursday)[0]["days"] == [
        "monday",
        "tuesday",
        "friday",
        "saturday",
    ]


def test_refuses_to_turn_off_the_last_day() -> None:
    """A schedule with no days is one the device cannot express."""
    one_day = build_schedule(
        [{"days": ["monday"], "start": "10:00", "duration_minutes": 60}]
    )

    with pytest.raises(ValueError):
        set_day(one_day, 0, "monday", False)
