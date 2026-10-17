# SPDX-FileCopyrightText: 2026 GARDENA GmbH
#
# SPDX-License-Identifier: Apache-2.0

"""The start time of each schedule a device holds, as an editable entity."""

from __future__ import annotations

import logging
from datetime import time
from functools import partial

from gardena_smart_local_api.devices.device import Device
from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import GardenaSmartLocalCoordinator
from .device_data import has_resource, read_value
from .entity import EntityFactories, GardenaEntity, async_setup_device_entities
from .schedules import describe_schedule, entry_count, replace_entry

_LOGGER = logging.getLogger(__name__)

# Writes go to the gateway's local websocket — cap at 1 so Home Assistant
# serializes them instead of rebuilding the same schedule twice at once
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: GardenaSmartLocalCoordinator = entry.runtime_data

    def _entities_for_device(device: Device) -> EntityFactories:
        entities: EntityFactories = {}
        if not has_resource(device, "lemonbeat", "schedule_config"):
            return entities
        raw = read_value(device, "lemonbeat", "schedule_config")
        # One entity per schedule the device actually holds, so slots appear
        # and disappear with the schedule itself
        for index in range(entry_count(raw if isinstance(raw, bytes) else None)):
            entities[f"schedule_start_{index}"] = partial(
                GardenaScheduleStartTime, coordinator, device, index
            )
        return entities

    async_setup_device_entities(
        entry, coordinator, async_add_entities, _entities_for_device
    )


class GardenaScheduleStartTime(GardenaEntity, TimeEntity):
    """When one of the device's schedules starts."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "schedule_start"
    _attr_icon = "mdi:clock-edit-outline"

    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Device,
        index: int,
    ) -> None:
        super().__init__(coordinator, device)
        self._index = index
        self._attr_unique_id = f"{device.id}_schedule_start_{index}"
        self._attr_translation_placeholders = {"number": str(index + 1)}

    def _schedule(self) -> bytes | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        raw = read_value(device, "lemonbeat", "schedule_config")
        return raw if isinstance(raw, bytes) else None

    @property
    def native_value(self) -> time | None:
        raw = self._schedule()
        if raw is None:
            return None
        entries = describe_schedule(raw)
        if self._index >= len(entries):
            return None
        hour, _, minute = entries[self._index]["start"].partition(":")
        return time(int(hour), int(minute))

    async def async_set_value(self, value: time) -> None:
        raw = self._schedule()
        if raw is None:
            return
        config = replace_entry(
            raw, self._index, start=f"{value.hour:02d}:{value.minute:02d}"
        )
        await self._send_confirmed_command(
            self._device.build_set_resource_obj(
                "lemonbeat", 0, "schedule_config", config
            )
        )
        _LOGGER.info(
            "Set schedule %s on device %s to start at %s",
            self._index + 1,
            self._device.id,
            value,
        )
