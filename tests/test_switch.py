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
