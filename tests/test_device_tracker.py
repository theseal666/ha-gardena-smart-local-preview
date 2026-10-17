# SPDX-FileCopyrightText: 2026 GARDENA GmbH
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for the GARDENA smart local device tracker platform."""

from __future__ import annotations

import struct
from unittest.mock import MagicMock

import pytest
from gardena_smart_local_api.devices.mowers import Gen1MowerPosition

from custom_components.gardena_smart_local_preview.device_tracker import (
    GardenaMowerTracker,
)


def _position(
    *,
    lona_latitude: int = 0,
    lona_longitude: int = 0,
    lona_is_ready: bool = False,
    gnss_latitude: int = 0,
    gnss_longitude: int = 0,
    accuracy: int = 0,
) -> Gen1MowerPosition:
    """Build a position from a raw frame, in the mower's 1e-7 degree units."""
    return Gen1MowerPosition.model_validate(
        struct.pack(
            ">2iI2ih?h?",
            gnss_latitude,
            gnss_longitude,
            accuracy,
            lona_latitude,
            lona_longitude,
            900,
            lona_is_ready,
            1800,
            True,
        )
    )


def test_prefers_the_lona_fix(coordinator: MagicMock, mock_device: MagicMock) -> None:
    """The fix the mower navigates by wins over the raw GNSS one."""
    mock_device.position = _position(
        lona_latitude=578947905,
        lona_longitude=119506228,
        lona_is_ready=True,
        gnss_latitude=578000000,
        gnss_longitude=119000000,
        accuracy=3,
    )
    tracker = GardenaMowerTracker(coordinator, mock_device)

    assert tracker.latitude == 57.8947905
    assert tracker.longitude == 11.9506228
    assert tracker.location_accuracy == 3


def test_falls_back_to_the_gnss_fix(
    coordinator: MagicMock, mock_device: MagicMock
) -> None:
    """Until LONA has a position, the GNSS fix is all there is."""
    mock_device.position = _position(
        gnss_latitude=578000000, gnss_longitude=119000000, accuracy=12
    )
    tracker = GardenaMowerTracker(coordinator, mock_device)

    assert tracker.latitude == pytest.approx(57.8)
    assert tracker.longitude == pytest.approx(11.9)
    assert tracker.location_accuracy == 12
    assert tracker.extra_state_attributes["lona_is_ready"] is False


def test_position_is_unknown_while_reporting_is_off(
    coordinator: MagicMock, mock_device: MagicMock
) -> None:
    """A mower that reports nothing has no position, not a position of 0, 0."""
    mock_device.position = None
    tracker = GardenaMowerTracker(coordinator, mock_device)

    assert tracker.latitude is None
    assert tracker.longitude is None
    assert tracker.location_accuracy == 0
    assert tracker.extra_state_attributes is None


def test_empty_frame_is_unknown(coordinator: MagicMock, mock_device: MagicMock) -> None:
    """A frame without either fix is reported as unknown."""
    mock_device.position = _position()
    tracker = GardenaMowerTracker(coordinator, mock_device)

    assert tracker.latitude is None
    assert tracker.longitude is None


def test_attributes_keep_the_rest_of_the_frame(
    coordinator: MagicMock, mock_device: MagicMock
) -> None:
    """Heading, the raw GNSS fix and the compass stay available."""
    mock_device.position = _position(
        lona_latitude=578947905,
        lona_longitude=119506228,
        lona_is_ready=True,
        gnss_latitude=578000000,
        gnss_longitude=119000000,
        accuracy=3,
    )
    tracker = GardenaMowerTracker(coordinator, mock_device)

    attributes = tracker.extra_state_attributes
    assert attributes["heading"] == 90.0
    assert attributes["compass_heading"] == 180.0
    assert attributes["compass_is_calibrated"] is True
    assert attributes["gnss_latitude"] == pytest.approx(57.8)
    assert attributes["gnss_horizontal_accuracy"] == 3
    # The coordinates themselves are the state, not an attribute
    assert "latitude" not in attributes
    assert "longitude" not in attributes
