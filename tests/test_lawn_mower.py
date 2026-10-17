# SPDX-FileCopyrightText: 2026 GARDENA GmbH
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for the GARDENA smart local lawn mower platform."""

from __future__ import annotations

from datetime import time
from unittest.mock import MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.gardena_smart_local_preview.const import (
    CONF_MOWER_DURATION,
    DEFAULT_MOWER_DURATION_HOURS,
)
from custom_components.gardena_smart_local_preview.lawn_mower import GardenaMower
from custom_components.gardena_smart_local_preview.schedules import describe_schedule


async def test_start_mowing_uses_default_duration(
    coordinator: MagicMock, entry: MagicMock, mock_device: MagicMock
) -> None:
    """Starting without a configured duration falls back to the default."""
    mower = GardenaMower(coordinator, entry, mock_device)

    await mower.async_start_mowing()

    mock_device.build_start_mowing_obj.assert_called_once_with(
        DEFAULT_MOWER_DURATION_HOURS * 3600
    )
    coordinator.send_request.assert_awaited_once()


async def test_start_mowing_uses_configured_duration(
    coordinator: MagicMock,
    entry: MagicMock,
    mock_device: MagicMock,
    subentry: MagicMock,
) -> None:
    """A duration stored in the device subentry is used for the start command."""
    subentry.data[CONF_MOWER_DURATION] = 2
    mower = GardenaMower(coordinator, entry, mock_device)

    await mower.async_start_mowing()

    mock_device.build_start_mowing_obj.assert_called_once_with(7200)


async def test_start_mowing_for_uses_override_duration(
    coordinator: MagicMock,
    entry: MagicMock,
    mock_device: MagicMock,
    subentry: MagicMock,
) -> None:
    """An explicit duration overrides the configured default for one call."""
    subentry.data[CONF_MOWER_DURATION] = 2
    mower = GardenaMower(coordinator, entry, mock_device)

    await mower.async_start_mowing_for(duration=4)

    mock_device.build_start_mowing_obj.assert_called_once_with(4 * 3600)


async def test_dock_stops_mowing(
    coordinator: MagicMock, entry: MagicMock, mock_device: MagicMock
) -> None:
    """Docking builds the stop command."""
    mower = GardenaMower(coordinator, entry, mock_device)

    await mower.async_dock()

    mock_device.build_stop_mowing_obj.assert_called_once_with()


async def test_start_mowing_with_a_distance_from_the_station(
    coordinator: MagicMock, entry: MagicMock, mock_device: MagicMock
) -> None:
    """A distance sends the manual start to a far corner of the garden."""
    mock_device.model_definition.objects = {
        "lemonbeat": {"resources": {"mower_timer_with_distance": {}}}
    }
    mower = GardenaMower(coordinator, entry, mock_device)

    await mower.async_start_mowing_for(duration=2, distance=20)

    mock_device.build_start_mowing_obj.assert_called_once_with(7200, 20)


async def test_start_mowing_rejects_a_distance_the_mower_cannot_use(
    coordinator: MagicMock, entry: MagicMock, mock_device: MagicMock
) -> None:
    """A mower without the resource is not sent a command it cannot answer."""
    mock_device.model_definition.objects = {"lemonbeat": {"resources": {}}}
    mower = GardenaMower(coordinator, entry, mock_device)

    with pytest.raises(HomeAssistantError):
        await mower.async_start_mowing_for(distance=20)

    mock_device.build_start_mowing_obj.assert_not_called()


async def test_set_schedule_writes_the_whole_list(
    coordinator: MagicMock, entry: MagicMock, mock_device: MagicMock
) -> None:
    """The service replaces the device's schedule with what it was given."""
    mock_device.model_definition.objects = {
        "lemonbeat": {"resources": {"schedule_config": {}}}
    }
    mower = GardenaMower(coordinator, entry, mock_device)

    await mower.async_set_schedule(
        [
            {
                "days": ["monday", "tuesday"],
                "start": time(7, 15),
                "duration_minutes": 120,
            }
        ]
    )

    mock_device.build_set_resource_obj.assert_called_once()
    args = mock_device.build_set_resource_obj.call_args.args
    assert args[:3] == ("lemonbeat", 0, "schedule_config")
    assert describe_schedule(args[3]) == [
        {"days": ["monday", "tuesday"], "start": "07:15", "duration_minutes": 120}
    ]


async def test_set_schedule_refuses_a_device_without_one(
    coordinator: MagicMock, entry: MagicMock, mock_device: MagicMock
) -> None:
    """A device with no schedule resource is not written to."""
    mock_device.model_definition.objects = {"lemonbeat": {"resources": {}}}
    mower = GardenaMower(coordinator, entry, mock_device)

    with pytest.raises(HomeAssistantError):
        await mower.async_set_schedule(
            [{"days": ["monday"], "start": time(9, 0), "duration_minutes": 60}]
        )

    mock_device.build_set_resource_obj.assert_not_called()
