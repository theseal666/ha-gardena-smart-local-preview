# SPDX-FileCopyrightText: 2026 GARDENA GmbH
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for the GARDENA smart local button platform."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.gardena_smart_local_preview.button import (
    GardenaRefreshDataButton,
)


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
