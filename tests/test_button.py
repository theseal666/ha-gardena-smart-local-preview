# SPDX-FileCopyrightText: 2026 GARDENA GmbH
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for the GARDENA smart local button platform."""

from __future__ import annotations

from unittest.mock import MagicMock

from gardena_smart_local_api.messages import EgressMessageList

from custom_components.gardena_smart_local_preview.button import (
    GardenaRefreshDataButton,
)


async def test_refresh_data_asks_the_device_to_report(
    coordinator: MagicMock, mock_device: MagicMock
) -> None:
    """Pressing sends the model's own data-update command."""
    mock_device.get_command.return_value = 21
    mock_device.model_definition.objects = {}
    mock_device.build_command_obj.return_value = EgressMessageList([])
    button = GardenaRefreshDataButton(coordinator, mock_device)

    await button.async_press()

    mock_device.get_command.assert_called_once_with("trigger_data_update")
    mock_device.build_command_obj.assert_called_once_with(21)
    coordinator.send_request.assert_awaited_once()


async def test_refresh_data_also_reads_what_the_command_misses(
    coordinator: MagicMock, mock_device: MagicMock
) -> None:
    """The command leaves the error resource and status message untouched."""
    mock_device.get_command.return_value = 21
    mock_device.model_definition.objects = {
        "device": {"resources": {"error_code": {}}},
        "lemonbeat_status_message": {"resources": {"code": {}, "level": {}}},
    }
    mock_device.build_command_obj.return_value = EgressMessageList([])
    mock_device.build_read_value_obj.return_value = EgressMessageList([])
    button = GardenaRefreshDataButton(coordinator, mock_device)

    await button.async_press()

    read_paths = [
        str(call.args[0]) for call in mock_device.build_read_value_obj.call_args_list
    ]
    assert read_paths == [
        "device/0/error_code",
        "lemonbeat_status_message/0/code",
        "lemonbeat_status_message/0/level",
    ]
    # One request to the gateway, not one per resource
    coordinator.send_request.assert_awaited_once()
