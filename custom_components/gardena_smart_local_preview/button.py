# SPDX-FileCopyrightText: 2026 GARDENA GmbH
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import logging
from functools import partial

from gardena_smart_local_api.devices import Pump
from gardena_smart_local_api.devices.device import Device
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import GardenaSmartLocalCoordinator
from .device_data import has_command, read_value
from .entity import EntityFactories, GardenaEntity, async_setup_device_entities
from .schedules import (
    MAX_SCHEDULES,
    WEEKDAYS,
    add_entry,
    entry_count,
    remove_entry,
)

_LOGGER = logging.getLogger(__name__)

# Actions send commands to the gateway's local websocket — cap at 1 so HA
# serializes them instead of firing concurrent commands at the same connection
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: GardenaSmartLocalCoordinator = entry.runtime_data

    def _entities_for_device(device: Device) -> EntityFactories:
        entities: EntityFactories = {}
        if hasattr(device, "build_identify_obj"):
            entities["identify"] = partial(GardenaIdentifyButton, coordinator, device)
        if isinstance(device, Pump):
            entities["reset_flow"] = partial(
                GardenaPumpResetFlowButton, coordinator, device
            )
            entities["reset_valve_errors"] = partial(
                GardenaPumpResetValveErrorsButton, coordinator, device
            )
            entities["reset_temperature_min_max"] = partial(
                GardenaPumpResetTemperatureMinMaxButton, coordinator, device
            )
        if hasattr(device, "schedule_count"):
            entities["clear_schedules"] = partial(
                GardenaClearSchedulesButton, coordinator, device
            )
        if has_command(device, "trigger_data_update"):
            entities["refresh_data"] = partial(
                GardenaRefreshDataButton, coordinator, device
            )
        if has_command(device, "trigger_guide_wire_length_measurement"):
            entities["measure_guide_wire"] = partial(
                GardenaMeasureGuideWireButton, coordinator, device
            )
        for command, name in WIPE_BUTTONS.items():
            if has_command(device, command):
                entities[command] = partial(
                    GardenaWipeButton, coordinator, device, command, name
                )
        return entities

    async_setup_device_entities(
        entry, coordinator, async_add_entities, _entities_for_device
    )


class GardenaIdentifyButton(GardenaEntity, ButtonEntity):
    def __init__(
        self, coordinator: GardenaSmartLocalCoordinator, device: Device
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_identify"
        self._attr_translation_key = "identify"
        self._attr_icon = "mdi:crosshairs-gps"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_press(self) -> None:
        await self._send_confirmed_command(self._device.build_identify_obj())
        _LOGGER.info("Sent identify request for device %s", self._device.id)


class GardenaPumpResetFlowButton(GardenaEntity, ButtonEntity):
    def __init__(self, coordinator: GardenaSmartLocalCoordinator, device: Pump) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_reset_flow"
        self._attr_translation_key = "reset_resettable_flow"
        self._attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        await self._send_confirmed_command(
            self._device.build_reset_flow_resettable_obj()
        )
        _LOGGER.info("Reset resettable flow for device %s", self._device.id)


class GardenaPumpResetValveErrorsButton(GardenaEntity, ButtonEntity):
    def __init__(self, coordinator: GardenaSmartLocalCoordinator, device: Pump) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_reset_valve_errors"
        self._attr_translation_key = "reset_valve_errors"
        self._attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        await self._send_confirmed_command(
            self._device.build_reset_all_valve_errors_obj()
        )
        _LOGGER.info("Reset valve errors for device %s", self._device.id)


class GardenaPumpResetTemperatureMinMaxButton(GardenaEntity, ButtonEntity):
    def __init__(self, coordinator: GardenaSmartLocalCoordinator, device: Pump) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_reset_temperature_min_max"
        self._attr_translation_key = "reset_temperature_min_max"
        self._attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        await self._send_confirmed_command(
            self._device.build_reset_outlet_temperature_min_max_obj()
        )
        _LOGGER.info("Reset temperature min/max for device %s", self._device.id)


class GardenaClearSchedulesButton(GardenaEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "clear_schedules"
    _attr_icon = "mdi:delete-alert-outline"

    def __init__(
        self, coordinator: GardenaSmartLocalCoordinator, device: Device
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_clear_schedules"

    async def async_press(self) -> None:
        await self._send_confirmed_command(self._device.build_clear_schedules_obj())
        _LOGGER.info("Cleared schedules for device %s", self._device.id)


class GardenaRefreshDataButton(GardenaEntity, ButtonEntity):
    """Ask a device to report its current state again.

    A Gen1 device reports on change, so a value that has not changed can be
    days old and survives a Home Assistant restart that way: the mower this
    was written against served a three-day-old status and error code, which
    every entity reading them then presents as current. This asks the device
    for a fresh report instead of waiting for it to volunteer one.

    Measured scope, on a Gen1 mower: status, battery level, cutting time and
    the last error code all carry a fresh timestamp a second after the press.
    The standard error resource and the status message do not, and reading
    them explicitly does not change that — the gateway serves the value as the
    device last reported it, and the device reports those two only when they
    change. Their age is what the entities' `reported_at` attribute is for.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "refresh_data"
    _attr_icon = "mdi:refresh"

    def __init__(
        self, coordinator: GardenaSmartLocalCoordinator, device: Device
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_refresh_data"

    async def async_press(self) -> None:
        await self._send_confirmed_command(
            self._device.build_command_obj(
                self._device.get_command("trigger_data_update")
            )
        )
        _LOGGER.info("Requested a data update from device %s", self._device.id)


# What the mower has learnt about a garden, and the commands that throw it
# away. All off by default: they are not undoable, and a mower that has lost
# its map has to learn the garden again.
WIPE_BUTTONS = {
    "wipe_map": "wipe_map",
    "wipe_zones": "wipe_zones",
    "wipe_map_and_zones": "wipe_map_and_zones",
}


class GardenaMeasureGuideWireButton(GardenaEntity, ButtonEntity):
    """Ask the mower to measure its guide wire.

    The length it finds lands in the guide wire length sensor, and a reading
    that has changed is a wire that has been damaged, lengthened or shortened.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "measure_guide_wire"
    _attr_icon = "mdi:tape-measure"

    def __init__(
        self, coordinator: GardenaSmartLocalCoordinator, device: Device
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_measure_guide_wire"

    async def async_press(self) -> None:
        await self._send_confirmed_command(
            self._device.build_command_obj(
                self._device.get_command("trigger_guide_wire_length_measurement")
            )
        )
        _LOGGER.info("Started a guide wire measurement on device %s", self._device.id)


class GardenaWipeButton(GardenaEntity, ButtonEntity):
    """Throw away a map or the zones the mower has learnt."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_icon = "mdi:delete-alert-outline"

    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Device,
        command: str,
        translation_key: str,
    ) -> None:
        super().__init__(coordinator, device)
        self._command = command
        self._attr_unique_id = f"{device.id}_{command}"
        self._attr_translation_key = translation_key

    async def async_press(self) -> None:
        await self._send_confirmed_command(
            self._device.build_command_obj(self._device.get_command(self._command))
        )
        _LOGGER.info("Sent %s to device %s", self._command, self._device.id)


# What a newly added schedule starts out as, before it is edited: every day,
# mid-morning, two hours. Deliberately unremarkable — the entities next to it
# are how it gets its real shape.
NEW_SCHEDULE = {
    "days": list(WEEKDAYS),
    "start": "10:00",
    "duration_minutes": 120,
}


class GardenaScheduleButton(GardenaEntity, ButtonEntity):
    """Shared plumbing for the buttons that write a schedule."""

    _attr_entity_category = EntityCategory.CONFIG

    def _schedule(self) -> bytes | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        raw = read_value(device, "lemonbeat", "schedule_config")
        return raw if isinstance(raw, bytes) else None

    async def _async_write(self, config: bytes) -> None:
        await self._send_confirmed_command(
            self._device.build_set_resource_obj(
                "lemonbeat", 0, "schedule_config", config
            )
        )


class GardenaAddScheduleButton(GardenaScheduleButton):
    """Append a schedule to edit with the entities beside it."""

    _attr_translation_key = "add_schedule"
    _attr_icon = "mdi:calendar-plus"

    def __init__(
        self, coordinator: GardenaSmartLocalCoordinator, device: Device
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_add_schedule"

    async def async_press(self) -> None:
        raw = self._schedule()
        if entry_count(raw) >= MAX_SCHEDULES:
            raise HomeAssistantError(
                f"Device {self._device.id} already holds the {MAX_SCHEDULES} "
                f"schedules it can keep"
            )
        await self._async_write(add_entry(raw, NEW_SCHEDULE))
        _LOGGER.info("Added a schedule to device %s", self._device.id)


class GardenaRemoveScheduleButton(GardenaScheduleButton):
    """Drop one of the schedules the device holds."""

    _attr_translation_key = "remove_schedule"
    _attr_icon = "mdi:calendar-remove"

    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Device,
        index: int,
    ) -> None:
        super().__init__(coordinator, device)
        self._index = index
        self._attr_unique_id = f"{device.id}_remove_schedule_{index}"
        self._attr_translation_placeholders = {"number": str(index + 1)}

    async def async_press(self) -> None:
        raw = self._schedule()
        if raw is None:
            raise HomeAssistantError(f"Device {self._device.id} holds no schedule")
        try:
            config = remove_entry(raw, self._index)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        await self._async_write(config)
        _LOGGER.info(
            "Removed schedule %s from device %s", self._index + 1, self._device.id
        )
