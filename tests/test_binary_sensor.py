# SPDX-FileCopyrightText: 2026 GARDENA GmbH
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for the GARDENA smart local binary sensor platform."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from gardena_smart_local_api.devices import MowerState

from custom_components.gardena_smart_local_preview.binary_sensor import (
    GardenaConnectionSensor,
    GardenaProblemSensor,
)


@pytest.fixture
def mower(mock_device: MagicMock) -> MagicMock:
    """A mower that is online, idle and resolving IPSO paths from a dict."""
    mock_device.is_online = True
    mock_device.state = MowerState.PARKED
    mock_device.model_definition.objects = {
        "lemonbeat": {"resources": {"last_error_code": {}}}
    }
    mock_device.get_value.side_effect = lambda path: {
        "lemonbeat/0/last_error_code": 0
    }.get(str(path))
    return mock_device


def test_connection_stays_available_when_the_device_goes_quiet(
    coordinator: MagicMock, mower: MagicMock
) -> None:
    """A silent device is reported as disconnected, not as unknown."""
    sensor = GardenaConnectionSensor(coordinator, mower)
    assert sensor.available is True
    assert sensor.is_on is True

    mower.is_online = False

    # Every other entity goes unavailable here; this one has to keep reporting
    assert sensor.available is True
    assert sensor.is_on is False


def test_connection_is_unavailable_when_the_gateway_is(
    coordinator: MagicMock, mower: MagicMock
) -> None:
    """A gateway this integration cannot reach is the third, separate case."""
    coordinator.connected = False
    sensor = GardenaConnectionSensor(coordinator, mower)

    assert sensor.available is False


def test_problem_follows_the_mower_state(
    coordinator: MagicMock, mower: MagicMock
) -> None:
    """A mower in its error state needs someone to go out to it."""
    sensor = GardenaProblemSensor(coordinator, mower)
    assert sensor.is_on is False

    mower.state = MowerState.ERROR
    assert sensor.is_on is True


def test_problem_follows_a_logged_error_code(
    coordinator: MagicMock, mower: MagicMock
) -> None:
    """A code the mower has logged counts even if its state has moved on."""
    mower.get_value.side_effect = lambda path: {"lemonbeat/0/last_error_code": 2}.get(
        str(path)
    )
    sensor = GardenaProblemSensor(coordinator, mower)

    assert sensor.is_on is True
