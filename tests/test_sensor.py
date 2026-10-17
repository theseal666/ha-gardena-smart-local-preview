# SPDX-FileCopyrightText: 2026 GARDENA GmbH
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for the GARDENA smart local sensor platform."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.gardena_smart_local_preview.sensor import (
    GardenaErrorCodeSensor,
    GardenaLastErrorCodeSensor,
    GardenaLastErrorTimeSensor,
    GardenaStatusMessageCodeSensor,
)


@pytest.fixture
def values(mock_device: MagicMock) -> dict[str, object]:
    """Let the device mock resolve IPSO paths from a dict the test fills."""
    reported: dict[str, object] = {}
    mock_device.get_value.side_effect = lambda path: reported.get(str(path))
    return reported


def test_error_code_reports_the_first_active_code(
    coordinator: MagicMock, mock_device: MagicMock, values: dict[str, object]
) -> None:
    """The state is the active code, with every reported code as an attribute."""
    values["device/0/error_code"] = [0, 13]
    sensor = GardenaErrorCodeSensor(coordinator, mock_device)

    assert sensor.native_value == 13
    assert sensor.extra_state_attributes == {"error_codes": [0, 13]}


def test_error_code_is_zero_without_an_error(
    coordinator: MagicMock, mock_device: MagicMock, values: dict[str, object]
) -> None:
    """A device that only reports the "no error" entry is not in error."""
    values["device/0/error_code"] = [0]
    sensor = GardenaErrorCodeSensor(coordinator, mock_device)

    assert sensor.native_value == 0


def test_error_code_is_unknown_until_reported(
    coordinator: MagicMock, mock_device: MagicMock, values: dict[str, object]
) -> None:
    """Nothing is made up before the device has reported the resource."""
    sensor = GardenaErrorCodeSensor(coordinator, mock_device)

    assert sensor.native_value is None
    assert sensor.extra_state_attributes is None


def test_last_error_code_is_kept_after_the_error_cleared(
    coordinator: MagicMock, mock_device: MagicMock, values: dict[str, object]
) -> None:
    """The mower's own last-error resource is independent of the current one."""
    values["device/0/error_code"] = [0]
    values["lemonbeat/0/last_error_code"] = 13
    sensor = GardenaLastErrorCodeSensor(coordinator, mock_device)

    assert sensor.native_value == 13


async def test_last_error_time_is_reported_as_utc(
    hass: HomeAssistant,
    coordinator: MagicMock,
    mock_device: MagicMock,
    values: dict[str, object],
) -> None:
    """The device's local timestamp becomes an aware UTC datetime."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    values["lemonbeat/0/timestamp_last_error_code"] = (1791990715).to_bytes(4)
    sensor = GardenaLastErrorTimeSensor(coordinator, mock_device)

    assert sensor.native_value == datetime(2026, 10, 14, 13, 11, 55, tzinfo=UTC)


def test_status_message_resolves_the_level(
    coordinator: MagicMock, mock_device: MagicMock, values: dict[str, object]
) -> None:
    """The message's numeric level is named, the rest is passed through."""
    values["lemonbeat_status_message/0/code"] = 10
    values["lemonbeat_status_message/0/level"] = 2
    values["lemonbeat_status_message/0/type"] = 200
    values["lemonbeat_status_message/0/data"] = "000025"
    sensor = GardenaStatusMessageCodeSensor(coordinator, mock_device)

    assert sensor.native_value == 10
    assert sensor.extra_state_attributes == {
        "level": "error",
        "message_type": 200,
        "data": "000025",
    }
