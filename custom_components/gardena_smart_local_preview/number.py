# SPDX-FileCopyrightText: 2026 GARDENA GmbH
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import logging
from functools import partial

from gardena_smart_local_api.devices import PowerAdapter, Pump
from gardena_smart_local_api.devices.device import Device
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfPressure, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import GardenaSmartLocalCoordinator
from .device_data import has_resource, read_int, read_value
from .entity import (
    EntityFactories,
    GardenaEntity,
    async_set_mower_duration_hours,
    async_set_power_duration_minutes,
    async_set_pump_duration_minutes,
    async_set_valve_duration_minutes,
    async_setup_device_entities,
    get_mower_duration_hours,
    get_power_duration_minutes,
    get_pump_duration_minutes,
    get_valve_duration_minutes,
)
from .schedules import describe_schedule, entry_count, replace_entry

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
        if hasattr(device, "build_set_button_config_time_obj"):
            for valve_id in device.valve_ids:
                entities[f"button_watering_duration_{valve_id}"] = partial(
                    GardenaButtonConfigTime, coordinator, device, valve_id
                )
        elif isinstance(device, Pump):
            entities["turn_on_pressure"] = partial(
                GardenaPumpTurnOnPressure, coordinator, device
            )
            entities["pump_duration"] = partial(
                GardenaPumpDuration, coordinator, entry, device
            )
        elif isinstance(device, PowerAdapter):
            entities["power_duration"] = partial(
                GardenaPowerDuration, coordinator, entry, device
            )
        elif hasattr(device, "build_start_mowing_obj"):
            entities["mower_duration"] = partial(
                GardenaMowerDuration, coordinator, entry, device
            )
        if has_resource(device, "lemonbeat", "schedule_config"):
            raw = read_value(device, "lemonbeat", "schedule_config")
            for index in range(entry_count(raw if isinstance(raw, bytes) else None)):
                entities[f"schedule_duration_{index}"] = partial(
                    GardenaScheduleDuration, coordinator, device, index
                )
        if has_resource(device, "lemonbeat", "position_update_interval"):
            entities["position_update_interval"] = partial(
                GardenaPositionUpdateInterval, coordinator, device
            )
        for valve_id in getattr(device, "valve_ids", []):
            entities[f"valve_duration_{valve_id}"] = partial(
                GardenaValveDuration, coordinator, entry, device, valve_id
            )
        return entities

    async_setup_device_entities(
        entry, coordinator, async_add_entities, _entities_for_device
    )


class GardenaButtonConfigTime(GardenaEntity, NumberEntity):
    _attr_native_min_value = 0
    _attr_native_max_value = 90
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Device,
        valve_id: int = 0,
    ) -> None:
        super().__init__(coordinator, device)
        self._valve_id = valve_id
        multi_valve = len(device.valve_ids) > 1
        suffix = f"_{valve_id}" if multi_valve else ""
        self._attr_unique_id = f"{device.id}_button_config_time{suffix}"
        if multi_valve:
            self._attr_translation_key = "button_watering_duration_numbered"
            self._attr_translation_placeholders = {"number": str(valve_id + 1)}
        else:
            self._attr_translation_key = "button_watering_duration"
        self._attr_icon = "mdi:timer-outline"

    @property
    def native_value(self) -> float | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        if hasattr(device, "get_button_config_time"):
            seconds = device.get_button_config_time(self._valve_id)
        else:
            seconds = device.button_config_time
        if seconds is None:
            return None
        return round(seconds / 60)

    async def async_set_native_value(self, value: float) -> None:
        seconds = int(value) * 60
        if hasattr(self._device, "get_button_config_time"):
            request = self._device.build_set_button_config_time_obj(
                seconds, self._valve_id
            )
        else:
            request = self._device.build_set_button_config_time_obj(seconds)
        await self._send_confirmed_command(request)
        _LOGGER.info(
            "Set button config time for device %s, valve %s to %s minutes",
            self._device.id,
            self._valve_id,
            int(value),
        )


class GardenaPumpTurnOnPressure(GardenaEntity, NumberEntity):
    _attr_native_min_value = 0.0
    _attr_native_max_value = 10.0
    _attr_native_step = 0.1
    _attr_native_unit_of_measurement = UnitOfPressure.BAR
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Pump,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_turn_on_pressure"
        self._attr_translation_key = "turn_on_pressure"

    @property
    def native_value(self) -> float | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        return device.turn_on_pressure

    async def async_set_native_value(self, value: float) -> None:
        await self._send_confirmed_command(
            self._device.build_set_turn_on_pressure_obj(value)
        )
        _LOGGER.info(
            "Set turn-on pressure for device %s to %s bar",
            self._device.id,
            value,
        )


class GardenaValveDuration(GardenaEntity, NumberEntity):
    _attr_native_min_value = 1
    # Matches the ceiling the GARDENA app offers; how the firmware itself
    # handles the maximum is not validated yet.
    _attr_native_max_value = 180
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        entry: ConfigEntry,
        device: Device,
        valve_id: int,
    ) -> None:
        super().__init__(coordinator, device)
        self._entry = entry
        self._valve_id = valve_id
        self._attr_unique_id = f"{device.id}_valve_{valve_id}_duration"
        self._attr_name = (
            f"Valve {valve_id + 1} Default Watering Duration"
            if len(device.valve_ids) > 1
            else "Default Watering Duration"
        )
        self._attr_icon = "mdi:timer-outline"

    # Stored in the config subentry rather than read from the device, so it
    # stays settable while the gateway or the device itself is unreachable.
    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> float | None:
        return get_valve_duration_minutes(self._entry, self._device.id, self._valve_id)

    async def async_set_native_value(self, value: float) -> None:
        minutes = int(value)
        async_set_valve_duration_minutes(
            self.hass, self._entry, self._device.id, self._valve_id, minutes
        )
        self.async_write_ha_state()
        _LOGGER.info(
            "Set valve duration for device %s valve_id=%s to %s minutes",
            self._device.id,
            self._valve_id,
            minutes,
        )


class GardenaPowerDuration(GardenaEntity, NumberEntity):
    _attr_native_min_value = 1
    _attr_native_max_value = 180
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        entry: ConfigEntry,
        device: PowerAdapter,
    ) -> None:
        super().__init__(coordinator, device)
        self._entry = entry
        self._attr_unique_id = f"{device.id}_power_duration"
        self._attr_name = "Default On Duration"
        self._attr_icon = "mdi:timer-outline"

    # Stored in the config subentry rather than read from the device, so it
    # stays settable while the gateway or the device itself is unreachable.
    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> float | None:
        return get_power_duration_minutes(self._entry, self._device.id)

    async def async_set_native_value(self, value: float) -> None:
        minutes = int(value)
        async_set_power_duration_minutes(
            self.hass, self._entry, self._device.id, minutes
        )
        self.async_write_ha_state()
        _LOGGER.info(
            "Set power outlet duration for device %s to %s minutes",
            self._device.id,
            minutes,
        )


class GardenaPumpDuration(GardenaEntity, NumberEntity):
    _attr_native_min_value = 1
    # Matches the ceiling the GARDENA app offers for pumps.
    _attr_native_max_value = 90
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        entry: ConfigEntry,
        device: Pump,
    ) -> None:
        super().__init__(coordinator, device)
        self._entry = entry
        self._attr_unique_id = f"{device.id}_pump_duration"
        self._attr_name = "Default Run Duration"
        self._attr_icon = "mdi:timer-outline"

    # Stored in the config subentry rather than read from the device, so it
    # stays settable while the gateway or the device itself is unreachable.
    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> float | None:
        return get_pump_duration_minutes(self._entry, self._device.id)

    async def async_set_native_value(self, value: float) -> None:
        minutes = int(value)
        async_set_pump_duration_minutes(
            self.hass, self._entry, self._device.id, minutes
        )
        self.async_write_ha_state()
        _LOGGER.info(
            "Set pump duration for device %s to %s minutes",
            self._device.id,
            minutes,
        )


class GardenaMowerDuration(GardenaEntity, NumberEntity):
    _attr_native_min_value = 1
    # Matches the maximum the GARDENA app offers.
    _attr_native_max_value = 6
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        entry: ConfigEntry,
        device: Device,
    ) -> None:
        super().__init__(coordinator, device)
        self._entry = entry
        self._attr_unique_id = f"{device.id}_mower_duration"
        self._attr_name = "Default Mowing Duration"
        self._attr_icon = "mdi:timer-outline"

    # Stored in the config subentry rather than read from the device, so it
    # stays settable while the gateway or the device itself is unreachable.
    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> float | None:
        return get_mower_duration_hours(self._entry, self._device.id)

    async def async_set_native_value(self, value: float) -> None:
        hours = int(value)
        async_set_mower_duration_hours(self.hass, self._entry, self._device.id, hours)
        self.async_write_ha_state()
        _LOGGER.info(
            "Set mower duration for device %s to %s hours",
            self._device.id,
            hours,
        )


class GardenaPositionUpdateInterval(GardenaEntity, NumberEntity):
    """How often a mower reports its position while reporting is on."""

    _attr_native_min_value = 1
    # The resource takes up to an hour, but an interval beyond a minute is of
    # no use for following a mower around the garden.
    _attr_native_max_value = 60
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "position_update_interval"

    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Device,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_position_update_interval"
        self._attr_icon = "mdi:timer-outline"

    @property
    def native_value(self) -> float | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        # The device keeps this one in milliseconds.
        milliseconds = read_int(device, "lemonbeat", "position_update_interval")
        return None if milliseconds is None else milliseconds / 1000

    async def async_set_native_value(self, value: float) -> None:
        milliseconds = int(value * 1000)
        await self._send_confirmed_command(
            self._device.build_set_resource_obj(
                "lemonbeat", 0, "position_update_interval", milliseconds
            )
        )
        _LOGGER.info(
            "Set position update interval for device %s to %s ms",
            self._device.id,
            milliseconds,
        )


class GardenaScheduleDuration(GardenaEntity, NumberEntity):
    """How long one of the device's schedules runs."""

    _attr_native_min_value = 1
    # A day. The resource holds two bytes and the device would take more, but
    # a single entry that outlasts a day is a schedule for something else.
    _attr_native_max_value = 1440
    _attr_native_step = 5
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.BOX
    _attr_translation_key = "schedule_duration"
    _attr_icon = "mdi:timer-edit-outline"

    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Device,
        index: int,
    ) -> None:
        super().__init__(coordinator, device)
        self._index = index
        self._attr_unique_id = f"{device.id}_schedule_duration_{index}"
        self._attr_translation_placeholders = {"number": str(index + 1)}

    def _schedule(self) -> bytes | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        raw = read_value(device, "lemonbeat", "schedule_config")
        return raw if isinstance(raw, bytes) else None

    @property
    def native_value(self) -> float | None:
        raw = self._schedule()
        if raw is None:
            return None
        entries = describe_schedule(raw)
        if self._index >= len(entries):
            return None
        return entries[self._index]["duration_minutes"]

    async def async_set_native_value(self, value: float) -> None:
        raw = self._schedule()
        if raw is None:
            return
        config = replace_entry(raw, self._index, duration_minutes=int(value))
        await self._send_confirmed_command(
            self._device.build_set_resource_obj(
                "lemonbeat", 0, "schedule_config", config
            )
        )
        _LOGGER.info(
            "Set schedule %s on device %s to %s minutes",
            self._index + 1,
            self._device.id,
            int(value),
        )
