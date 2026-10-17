# SPDX-FileCopyrightText: 2026 GARDENA GmbH
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for the GARDENA smart local button platform."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.gardena_smart_local_preview.button import (
    GardenaAddScheduleButton,
    GardenaMeasureGuideWireButton,
    GardenaRefreshDataButton,
    GardenaWipeButton,
)
from custom_components.gardena_smart_local_preview.schedules import describe_schedule


async def test_refresh_data_asks_the_device_to_report(
    coordinator: MagicMock, mock_device: MagicMock
) -> None:
    """Pressing sends the model's own data-update command."""
    mock_device.get_command.return_value = 21
    button = GardenaRefreshDataButton(coordinator, mock_device)

    await button.async_press()

    mock_device.get_command.assert_called_once_with("trigger_data_update")
    mock_device.build_command_obj.assert_called_once_with(21)
    coordinator.send_request.assert_awaited_once()


async def test_measure_guide_wire_sends_the_measurement_command(
    coordinator: MagicMock, mock_device: MagicMock
) -> None:
    """The button asks the mower to measure, it does not invent a length."""
    mock_device.get_command.return_value = 51
    button = GardenaMeasureGuideWireButton(coordinator, mock_device)

    await button.async_press()

    mock_device.get_command.assert_called_once_with(
        "trigger_guide_wire_length_measurement"
    )
    mock_device.build_command_obj.assert_called_once_with(51)


async def test_wipe_button_sends_its_own_command(
    coordinator: MagicMock, mock_device: MagicMock
) -> None:
    """Each wipe button carries the command it was built for."""
    mock_device.get_command.return_value = 49
    button = GardenaWipeButton(
        coordinator, mock_device, "wipe_map_and_zones", "Erases both."
    )

    await button.async_press()

    mock_device.get_command.assert_called_once_with("wipe_map_and_zones")
    mock_device.build_command_obj.assert_called_once_with(49)


def test_wipe_buttons_are_off_by_default(
    coordinator: MagicMock, mock_device: MagicMock
) -> None:
    """Wiping what a mower has learnt is not undoable."""
    button = GardenaWipeButton(coordinator, mock_device, "wipe_map", "Erases the map.")

    assert button.entity_registry_enabled_default is False
    # What it costs travels with the button, not only with the documentation
    assert button.extra_state_attributes["what_this_erases"] == "Erases the map."


async def test_add_schedule_appends_to_what_the_device_holds(
    coordinator: MagicMock, mock_device: MagicMock
) -> None:
    """Adding leaves the schedules already there alone."""
    held = bytes.fromhex("80760a1eb40000")
    mock_device.model_definition.objects = {
        "lemonbeat": {"resources": {"schedule_config": {}}}
    }
    mock_device.get_value.side_effect = lambda path: {
        "lemonbeat/0/schedule_config": held
    }.get(str(path))
    button = GardenaAddScheduleButton(coordinator, mock_device)

    await button.async_press()

    args = mock_device.build_set_resource_obj.call_args.args
    assert args[:3] == ("lemonbeat", 0, "schedule_config")
    assert len(describe_schedule(args[3])) == 2
    assert describe_schedule(args[3])[0]["start"] == "10:30"
