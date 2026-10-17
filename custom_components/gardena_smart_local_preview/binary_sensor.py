# SPDX-FileCopyrightText: 2026 GARDENA GmbH
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from functools import partial

from gardena_smart_local_api.devices import MowerState
from gardena_smart_local_api.devices.device import Device
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import GardenaSmartLocalCoordinator
from .device_data import has_resource, read_int
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
        if hasattr(device, "has_frost_warning"):
            entities["frost_warning"] = partial(
                GardenaFrostWarningSensor, coordinator, device
            )
        entities["connection"] = partial(GardenaConnectionSensor, coordinator, device)
        if hasattr(device, "state"):
            entities["problem"] = partial(GardenaProblemSensor, coordinator, device)
        return entities

    async_setup_device_entities(
        entry, coordinator, async_add_entities, _entities_for_device
    )


class GardenaFrostWarningSensor(GardenaEntity, BinarySensorEntity):
    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Device,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_frost_warning"
        self._attr_translation_key = "frost_warning"
        self._attr_device_class = BinarySensorDeviceClass.COLD
        self._attr_icon = "mdi:snowflake-alert"

    @property
    def is_on(self) -> bool | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        return device.has_frost_warning


class GardenaConnectionSensor(GardenaEntity, BinarySensorEntity):
    """Whether the device is answering the gateway.

    This separates two things that otherwise both read as `unavailable`: a
    gateway this integration cannot reach, and a device that has stopped
    answering it. A mower left in an unresolved error does the latter — the
    one measured for this went quiet 45 minutes after it faulted and stayed
    quiet for nearly two hours.

    So: `on` means the device is talking, `off` means it is not and the
    gateway is fine, and the entity itself going unavailable means the
    gateway or the integration is the problem.
    """

    # Only the gateway connection decides this one's availability
    _requires_device_online = False

    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Device,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_connection"
        self._attr_translation_key = "connection"
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        return device.is_online


class GardenaProblemSensor(GardenaEntity, BinarySensorEntity):
    """Whether the mower needs someone to go out to it.

    On while the mower reports an error, whether that is its state or an
    error code it has logged. Distinct from the connection sensor: a mower
    can be perfectly reachable and still stuck, and it can be silent for
    reasons of its own.
    """

    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Device,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_problem"
        self._attr_translation_key = "problem"
        self._attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self) -> bool | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        if device.state == MowerState.ERROR:
            return True
        if has_resource(device, "lemonbeat", "last_error_code"):
            code = read_int(device, "lemonbeat", "last_error_code")
            if code:
                return True
        return False
