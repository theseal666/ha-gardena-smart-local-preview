# SPDX-FileCopyrightText: 2026 GARDENA GmbH
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for the GARDENA smart local switch platform."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.gardena_smart_local_preview.const import (
    POSITION_REPORTING_REARM_SECONDS,
    POSITION_REPORTING_SECONDS,
)
from custom_components.gardena_smart_local_preview.switch import (
    GardenaPositionReportingSwitch,
    GardenaRunScheduleSwitch,
)


@pytest.fixture
def values(mock_device: MagicMock) -> dict[str, object]:
    """Let the device mock resolve IPSO paths from a dict the test fills."""
    reported: dict[str, object] = {}
    mock_device.get_value.side_effect = lambda path: reported.get(str(path))
    return reported


@pytest.fixture
async def position_switch(
    hass: HomeAssistant, coordinator: MagicMock, mock_device: MagicMock
) -> AsyncGenerator[GardenaPositionReportingSwitch]:
    """Return a switch wired to hass, so it can schedule its re-requests."""
    switch = GardenaPositionReportingSwitch(coordinator, mock_device)
    switch.hass = hass
    yield switch
    # Removal cancels a pending re-request, which would otherwise outlive the test
    await switch.async_will_remove_from_hass()


def test_is_on_follows_the_running_session(
    position_switch: GardenaPositionReportingSwitch, values: dict[str, object]
) -> None:
    """The switch reflects the mower, not the last command sent to it."""
    assert position_switch.is_on is None

    values["lemonbeat/0/position_timer"] = 0
    assert position_switch.is_on is False

    values["lemonbeat/0/position_timer"] = 3600
    assert position_switch.is_on is True


async def test_turn_on_requests_the_longest_session(
    position_switch: GardenaPositionReportingSwitch, mock_device: MagicMock
) -> None:
    """Turning on asks for as much reporting as the mower accepts at once."""
    await position_switch.async_turn_on()

    mock_device.build_start_position_reporting_obj.assert_called_once_with(
        POSITION_REPORTING_SECONDS
    )


async def test_turn_off_stops_reporting(
    position_switch: GardenaPositionReportingSwitch, mock_device: MagicMock
) -> None:
    """Turning off writes the zero that ends the session."""
    await position_switch.async_turn_on()
    mock_device.build_start_position_reporting_obj.reset_mock()

    await position_switch.async_turn_off()

    mock_device.build_start_position_reporting_obj.assert_called_once_with(0)


async def test_reporting_is_extended_before_it_expires(
    hass: HomeAssistant,
    position_switch: GardenaPositionReportingSwitch,
    mock_device: MagicMock,
) -> None:
    """A session is re-requested, so mowing longer than an hour stays tracked."""
    await position_switch.async_turn_on()
    mock_device.build_start_position_reporting_obj.reset_mock()

    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=POSITION_REPORTING_REARM_SECONDS + 1)
    )
    await hass.async_block_till_done()

    mock_device.build_start_position_reporting_obj.assert_called_once_with(
        POSITION_REPORTING_SECONDS
    )


async def test_turn_off_stops_extending(
    hass: HomeAssistant,
    position_switch: GardenaPositionReportingSwitch,
    mock_device: MagicMock,
) -> None:
    """Nothing is sent after the switch is off."""
    await position_switch.async_turn_on()
    await position_switch.async_turn_off()
    mock_device.build_start_position_reporting_obj.reset_mock()

    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=POSITION_REPORTING_REARM_SECONDS + 1)
    )
    await hass.async_block_till_done()

    mock_device.build_start_position_reporting_obj.assert_not_called()


async def test_a_rejected_extension_stops_the_retries(
    hass: HomeAssistant,
    position_switch: GardenaPositionReportingSwitch,
    coordinator: MagicMock,
    mock_device: MagicMock,
) -> None:
    """A gateway that refuses the command is not asked again every interval."""
    await position_switch.async_turn_on()
    coordinator.send_request.side_effect = TimeoutError
    mock_device.build_start_position_reporting_obj.reset_mock()

    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=POSITION_REPORTING_REARM_SECONDS + 1)
    )
    await hass.async_block_till_done()
    assert mock_device.build_start_position_reporting_obj.call_count == 1

    mock_device.build_start_position_reporting_obj.reset_mock()
    async_fire_time_changed(
        hass,
        dt_util.utcnow() + timedelta(seconds=2 * POSITION_REPORTING_REARM_SECONDS + 2),
    )
    await hass.async_block_till_done()
    mock_device.build_start_position_reporting_obj.assert_not_called()


async def test_a_rejected_turn_on_is_reported(
    position_switch: GardenaPositionReportingSwitch, coordinator: MagicMock
) -> None:
    """Failing to start reporting surfaces instead of being swallowed."""
    coordinator.send_request.side_effect = TimeoutError

    with pytest.raises(HomeAssistantError):
        await position_switch.async_turn_on()


@pytest.fixture
def run_schedule(
    coordinator: MagicMock, mock_device: MagicMock, values: dict[str, object]
) -> GardenaRunScheduleSwitch:
    """A switch over the device's "paused until" resource."""
    return GardenaRunScheduleSwitch(coordinator, mock_device)


def test_run_schedule_reads_the_devices_pause(
    run_schedule: GardenaRunScheduleSwitch, values: dict[str, object]
) -> None:
    """A pause that has not run out is a parked mower, whoever parked it."""
    assert run_schedule.is_on is None

    # What a mower reports when nothing is paused
    values["lemonbeat/0/action_paused_until_1"] = (1970).to_bytes(2, "little") + bytes(
        [1, 1, 0, 0]
    )
    assert run_schedule.is_on is True

    # What docking writes
    values["lemonbeat/0/action_paused_until_1"] = (2042).to_bytes(2, "little") + bytes(
        [12, 31, 22, 0]
    )
    assert run_schedule.is_on is False


async def test_turning_the_schedule_on_writes_the_idle_value(
    run_schedule: GardenaRunScheduleSwitch, mock_device: MagicMock
) -> None:
    """Resuming writes back what a mower that was never parked reports."""
    await run_schedule.async_turn_on()

    args = mock_device.build_set_resource_obj.call_args.args
    assert args[:3] == ("lemonbeat", 0, "action_paused_until_1")
    assert (int.from_bytes(args[3][0:2], "little"), *args[3][2:]) == (1970, 1, 1, 0, 0)


async def test_turning_the_schedule_off_parks_the_mower(
    run_schedule: GardenaRunScheduleSwitch, mock_device: MagicMock
) -> None:
    """Off is the same park docking performs, not a second mechanism."""
    await run_schedule.async_turn_off()

    mock_device.build_stop_mowing_obj.assert_called_once_with()


def test_run_schedule_ignores_a_pause_that_has_run_out(
    run_schedule: GardenaRunScheduleSwitch, values: dict[str, object]
) -> None:
    """A pause in the past is over, not a parked mower."""
    values["lemonbeat/0/action_paused_until_1"] = (2020).to_bytes(2, "little") + bytes(
        [6, 1, 12, 0]
    )

    assert run_schedule.is_on is True


def test_run_schedule_is_unknown_for_a_frame_it_cannot_read(
    run_schedule: GardenaRunScheduleSwitch, values: dict[str, object]
) -> None:
    """A value of the wrong shape is not guessed at."""
    values["lemonbeat/0/action_paused_until_1"] = b"\x00\x00"

    assert run_schedule.is_on is None
