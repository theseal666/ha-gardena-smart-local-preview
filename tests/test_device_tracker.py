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
    """With both fixes in the same garden, the LONA one is the more precise."""
    mock_device.position = _position(
        lona_latitude=578947905,
        lona_longitude=119506228,
        lona_is_ready=True,
        # ~20 m away, as two fixes of one garden are
        gnss_latitude=578949705,
        gnss_longitude=119506228,
        accuracy=1104,
    )
    tracker = GardenaMowerTracker(coordinator, mock_device)

    assert tracker.latitude == pytest.approx(57.8947905)
    assert tracker.longitude == pytest.approx(11.9506228)
    assert tracker.extra_state_attributes["fix_source"] == "lona"


def test_rejects_a_lona_fix_from_another_garden(
    coordinator: MagicMock, mock_device: MagicMock
) -> None:
    """A mower that changed gardens still reports the old one as ready.

    Seen on a second-hand mower: a ready LONA fix 25 km from its own GNSS fix,
    which would otherwise put the mower in the previous owner's garden.
    """
    mock_device.position = _position(
        lona_latitude=576723413,
        lona_longitude=118645743,
        lona_is_ready=True,
        gnss_latitude=578947459,
        gnss_longitude=119504922,
        accuracy=1104,
    )
    tracker = GardenaMowerTracker(coordinator, mock_device)

    assert tracker.latitude == pytest.approx(57.8947459)
    assert tracker.longitude == pytest.approx(11.9504922)
    attributes = tracker.extra_state_attributes
    assert attributes["fix_source"] == "gnss"
    # The rejected fix stays visible rather than being dropped silently
    assert attributes["lona_latitude"] == pytest.approx(57.6723413)
    assert attributes["lona_longitude"] == pytest.approx(11.8645743)


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
    attributes = tracker.extra_state_attributes
    assert attributes["fix_source"] == "gnss"
    assert attributes["lona_is_ready"] is False
    assert attributes["lona_latitude"] is None


def test_uses_the_lona_fix_when_gnss_has_none(
    coordinator: MagicMock, mock_device: MagicMock
) -> None:
    """Without a GNSS fix there is nothing to cross-check against."""
    mock_device.position = _position(
        lona_latitude=578947905, lona_longitude=119506228, lona_is_ready=True
    )
    tracker = GardenaMowerTracker(coordinator, mock_device)

    assert tracker.latitude == pytest.approx(57.8947905)
    assert tracker.extra_state_attributes["fix_source"] == "lona"


def test_accuracy_is_not_published_as_metres(
    coordinator: MagicMock, mock_device: MagicMock
) -> None:
    """The frame's accuracy figure is in an undocumented unit.

    Home Assistant would draw `location_accuracy` as a radius in metres, and a
    mower sitting in its charging station reports 1104, so the figure is kept
    as an attribute instead.
    """
    mock_device.position = _position(
        gnss_latitude=578947459, gnss_longitude=119504922, accuracy=1104
    )
    tracker = GardenaMowerTracker(coordinator, mock_device)

    assert tracker.location_accuracy == 0
    assert tracker.extra_state_attributes["gnss_horizontal_accuracy"] == 1104


def test_position_is_unknown_while_reporting_is_off(
    coordinator: MagicMock, mock_device: MagicMock
) -> None:
    """A mower that reports nothing has no position, not a position of 0, 0."""
    mock_device.position = None
    tracker = GardenaMowerTracker(coordinator, mock_device)

    assert tracker.latitude is None
    assert tracker.longitude is None
    assert tracker.extra_state_attributes is None


def test_empty_frame_is_unknown(coordinator: MagicMock, mock_device: MagicMock) -> None:
    """A frame without either fix is reported as unknown."""
    mock_device.position = _position()
    tracker = GardenaMowerTracker(coordinator, mock_device)

    assert tracker.latitude is None
    assert tracker.longitude is None
    assert tracker.extra_state_attributes["fix_source"] is None


def test_attributes_keep_the_rest_of_the_frame(
    coordinator: MagicMock, mock_device: MagicMock
) -> None:
    """Heading, the raw GNSS fix and the compass stay available."""
    mock_device.position = _position(
        lona_latitude=578947905,
        lona_longitude=119506228,
        lona_is_ready=True,
        gnss_latitude=578949705,
        gnss_longitude=119506228,
        accuracy=3,
    )
    tracker = GardenaMowerTracker(coordinator, mock_device)

    attributes = tracker.extra_state_attributes
    assert attributes["heading"] == 90.0
    assert attributes["compass_heading"] == 180.0
    assert attributes["compass_is_calibrated"] is True
    assert attributes["gnss_latitude"] == pytest.approx(57.8949705)
    assert attributes["gnss_horizontal_accuracy"] == 3
    # The reported coordinates are the state, not an attribute
    assert "latitude" not in attributes
    assert "longitude" not in attributes
