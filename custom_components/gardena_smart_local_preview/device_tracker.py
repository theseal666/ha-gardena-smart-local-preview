# SPDX-FileCopyrightText: 2026 GARDENA GmbH
#
# SPDX-License-Identifier: Apache-2.0

"""Position of a GARDENA smart SILENO mower that reports one."""

from __future__ import annotations

from functools import partial
from typing import Any

from gardena_smart_local_api.devices.device import Device
from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import GardenaSmartLocalCoordinator
from .entity import EntityFactories, GardenaEntity, async_setup_device_entities

# State comes only from the coordinator's push (no polling, no actions) —
# there is nothing here for PARALLEL_UPDATES to throttle
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: GardenaSmartLocalCoordinator = entry.runtime_data

    def _entities_for_device(device: Device) -> EntityFactories:
        entities: EntityFactories = {}
        if hasattr(device, "position"):
            entities["position"] = partial(GardenaMowerTracker, coordinator, device)
        return entities

    async_setup_device_entities(
        entry, coordinator, async_add_entities, _entities_for_device
    )


class GardenaMowerTracker(GardenaEntity, TrackerEntity):
    """A mower's last reported position.

    Gen1 mowers only report while position reporting is switched on, and they
    report two fixes: the LONA one the mower navigates by, and the raw GNSS
    one. The LONA fix is preferred and the GNSS fix is the fallback for as
    long as LONA is not ready yet; the rest of the frame is kept as
    attributes.
    """

    _attr_source_type = SourceType.GPS
    _attr_translation_key = "position"
    _attr_icon = "mdi:crosshairs-gps"

    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Device,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_position"

    @property
    def _position(self) -> Any | None:
        device = self.coordinator.data.get(self._device.id)
        return getattr(device, "position", None) if device else None

    @property
    def _coordinates(self) -> tuple[float, float] | None:
        position = self._position
        if position is None:
            return None
        latitude = position.latitude
        longitude = position.longitude
        if not latitude and not longitude:
            # A Gen1 mower zeroes the LONA fix until LONA has a position.
            latitude = getattr(position, "gnss_latitude", 0.0)
            longitude = getattr(position, "gnss_longitude", 0.0)
        if not latitude and not longitude:
            return None
        return latitude, longitude

    @property
    def latitude(self) -> float | None:
        coordinates = self._coordinates
        return coordinates[0] if coordinates else None

    @property
    def longitude(self) -> float | None:
        coordinates = self._coordinates
        return coordinates[1] if coordinates else None

    @property
    def location_accuracy(self) -> int:
        position = self._position
        if position is None:
            return 0
        accuracy = getattr(
            position, "accuracy", getattr(position, "gnss_horizontal_accuracy", None)
        )
        return int(accuracy) if accuracy is not None else 0

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        position = self._position
        if position is None:
            return None
        # Everything the frame carries beyond the coordinates themselves:
        # heading, whether LONA has a fix, the raw GNSS fix and the compass.
        return position.model_dump(exclude={"latitude", "longitude"})
