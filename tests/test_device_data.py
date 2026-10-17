# SPDX-FileCopyrightText: 2026 GARDENA GmbH
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for the resource reads that go through a device's model definition."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant

from custom_components.gardena_smart_local_preview.device_data import (
    has_resource,
    read_int,
    read_int_list,
    read_local_timestamp,
)


def _device(values: dict[str, object] | None = None) -> MagicMock:
    """Return a device mock resolving IPSO paths from a dict."""
    device = MagicMock()
    device.model_definition.objects = {
        "lemonbeat": {"resources": {"last_error_code": {"type": "vi", "access": "r"}}},
        "connection_status": {},
    }
    device.get_value.side_effect = lambda path: (values or {}).get(str(path))
    return device


def test_has_resource_follows_the_model_definition() -> None:
    """A resource counts as present only if the model declares it."""
    device = _device()

    assert has_resource(device, "lemonbeat", "last_error_code") is True
    assert has_resource(device, "lemonbeat", "position") is False
    assert has_resource(device, "connection_status", "online") is False
    assert has_resource(device, "mower_app", "error") is False


def test_read_int_ignores_other_types() -> None:
    """Only integers are returned, so a bool never passes as a code."""
    device = _device(
        {
            "lemonbeat/0/last_error_code": 42,
            "lemonbeat/0/manual_operation": True,
            "device/0/model_number": "53988",
        }
    )

    assert read_int(device, "lemonbeat", "last_error_code") == 42
    assert read_int(device, "lemonbeat", "manual_operation") is None
    assert read_int(device, "device", "model_number") is None
    assert read_int(device, "lemonbeat", "never_reported") is None


def test_read_int_list_returns_all_codes() -> None:
    """An integer array resource is returned as it was reported."""
    device = _device({"device/0/error_code": [0, 13]})

    assert read_int_list(device, "device", "error_code") == [0, 13]
    assert read_int_list(device, "device", "never_reported") is None


async def test_read_local_timestamp_reads_wall_clock_time(hass: HomeAssistant) -> None:
    """The four raw bytes are a local wall-clock time, not a UTC epoch."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    # The device's count reads as 2026-10-14 15:11:55 on a local clock
    device = _device(
        {"lemonbeat/0/timestamp_last_error_code": (1791990715).to_bytes(4)}
    )

    assert read_local_timestamp(
        device, "lemonbeat", "timestamp_last_error_code"
    ) == datetime(2026, 10, 14, 13, 11, 55, tzinfo=UTC)


def test_read_local_timestamp_treats_zero_as_never() -> None:
    """A zero means the event never happened, not 1970."""
    device = _device(
        {
            "lemonbeat/0/timestamp_last_error_code": bytes(4),
            "lemonbeat/0/timestamp_next_start": b"\x00\x01",
        }
    )

    assert (
        read_local_timestamp(device, "lemonbeat", "timestamp_last_error_code") is None
    )
    # A frame of an unexpected length is reported as unknown rather than guessed
    assert read_local_timestamp(device, "lemonbeat", "timestamp_next_start") is None
    assert read_local_timestamp(device, "lemonbeat", "never_reported") is None
