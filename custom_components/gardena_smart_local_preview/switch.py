# SPDX-FileCopyrightText: 2026 GARDENA GmbH
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import logging
from datetime import timedelta
from functools import partial
from typing import Any

import voluptuous as vol
from gardena_smart_local_api.devices import PowerAdapter, Pump
from gardena_smart_local_api.devices.device import Device
from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from .const import POSITION_REPORTING_REARM_SECONDS, POSITION_REPORTING_SECONDS
from .coordinator import GardenaSmartLocalCoordinator
from .device_data import has_resource, read_int, read_value
from .entity import (
    EntityFactories,
    GardenaEntity,
    async_setup_device_entities,
    get_power_duration_minutes,
    get_pump_duration_minutes,
)
from .schedules import (
    NOT_PAUSED,
    WEEKDAYS,
    describe_schedule,
    entry_count,
    is_paused,
    set_day,
)

_LOGGER = logging.getLogger(__name__)

# Actions send commands to the gateway's local websocket — cap at 1 so HA
# serializes them instead of firing concurrent commands at the same connection
PARALLEL_UPDATES = 1

# used as "indefinitly" in the official app
DEFAULT_ON_DURATION_SECONDS = 16777216


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: GardenaSmartLocalCoordinator = entry.runtime_data

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "enable_output",
        {
            # min=1 only to avoid colliding with 0, which build_enable_output_obj
            # treats as "disable" rather than "on for 0 seconds". Unlike the
            # valve/pump, the outlet has no app-defined upper duration limit.
            vol.Optional("duration"): vol.All(vol.Coerce(int), vol.Range(min=1))
        },
        "async_turn_on_for",
    )
    platform.async_register_entity_service(
        "start_pump",
        {
            # Seconds, like open_valve/enable_output. 60-5400 (1-90 min) is the
            # duration range the official app offers for pumps.
            vol.Optional("duration"): vol.All(
                vol.Coerce(int), vol.Range(min=60, max=5400)
            )
        },
        "async_turn_on_for",
    )

    def _entities_for_device(device: Device) -> EntityFactories:
        entities: EntityFactories = {}
        if isinstance(device, PowerAdapter):
            entities["power"] = partial(GardenaPowerSwitch, coordinator, entry, device)
        elif isinstance(device, Pump):
            entities["pump"] = partial(GardenaPumpSwitch, coordinator, entry, device)
        if hasattr(device, "build_stop_mowing_obj") and has_resource(
            device, "lemonbeat", "action_paused_until_1"
        ):
            entities["run_schedule"] = partial(
                GardenaRunScheduleSwitch, coordinator, device
            )
        if has_resource(device, "lemonbeat", "schedule_config"):
            raw = read_value(device, "lemonbeat", "schedule_config")
            for index in range(entry_count(raw if isinstance(raw, bytes) else None)):
                for day in WEEKDAYS:
                    entities[f"schedule_{index}_{day}"] = partial(
                        GardenaScheduleDaySwitch, coordinator, device, index, day
                    )
        if hasattr(device, "build_start_position_reporting_obj"):
            entities["position_reporting"] = partial(
                GardenaPositionReportingSwitch, coordinator, device
            )
        return entities

    async_setup_device_entities(
        entry, coordinator, async_add_entities, _entities_for_device
    )


class GardenaPowerSwitch(GardenaEntity, SwitchEntity):
    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        entry: ConfigEntry,
        device: PowerAdapter,
    ) -> None:
        super().__init__(coordinator, device)
        self._entry = entry
        self._attr_unique_id = f"{device.id}_switch"
        self._attr_name = None
        self._attr_device_class = SwitchDeviceClass.OUTLET

    @property
    def is_on(self) -> bool | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        return device.is_output_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._send_confirmed_command(
            self._device.build_enable_output_obj(DEFAULT_ON_DURATION_SECONDS)
        )
        _LOGGER.info("Turning on switch %s", self._device.id)

    async def async_turn_on_for(self, duration: int | None = None) -> None:
        if duration is None:
            minutes = get_power_duration_minutes(self._entry, self._device.id)
            duration = minutes * 60
        await self._send_confirmed_command(
            self._device.build_enable_output_obj(duration)
        )
        _LOGGER.info(
            "Turning on switch %s duration=%s seconds", self._device.id, duration
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._send_confirmed_command(self._device.build_disable_output_obj())
        _LOGGER.info("Turning off switch %s", self._device.id)


class GardenaPumpSwitch(GardenaEntity, SwitchEntity):
    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        entry: ConfigEntry,
        device: Pump,
    ) -> None:
        super().__init__(coordinator, device)
        self._entry = entry
        self._attr_unique_id = f"{device.id}_switch"
        self._attr_name = None

    @property
    def is_on(self) -> bool | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        return device.is_running

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._send_confirmed_command(
            self._device.build_start_obj(DEFAULT_ON_DURATION_SECONDS)
        )
        _LOGGER.info("Turning on pump %s", self._device.id)

    async def async_turn_on_for(self, duration: int | None = None) -> None:
        if duration is None:
            minutes = get_pump_duration_minutes(self._entry, self._device.id)
            duration = minutes * 60
        await self._send_confirmed_command(self._device.build_start_obj(duration))
        _LOGGER.info("Starting pump %s duration=%s seconds", self._device.id, duration)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._send_confirmed_command(self._device.build_stop_obj())
        _LOGGER.info("Turning off pump %s", self._device.id)


class GardenaPositionReportingSwitch(GardenaEntity, SwitchEntity):
    """Position reporting of a mower that knows where it is.

    A mower reports its position only on request, and only for an hour at a
    time, so while this switch is on the request is repeated before it runs
    out. That keeps the mower's `device_tracker` entity fed for a whole mowing
    session.
    """

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_translation_key = "position_reporting"
    _attr_icon = "mdi:crosshairs-gps"

    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Device,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_position_reporting"
        self._cancel_rearm: CALLBACK_TYPE | None = None

    @property
    def is_on(self) -> bool | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        remaining = read_int(device, "lemonbeat", "position_timer")
        return None if remaining is None else remaining > 0

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Reporting keeps running across a Home Assistant restart, so take the
        # re-requesting back over instead of letting it expire unnoticed.
        if self.is_on:
            self._schedule_rearm()

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_pending_rearm()
        await super().async_will_remove_from_hass()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_request_reporting(POSITION_REPORTING_SECONDS)
        self._schedule_rearm()
        _LOGGER.info("Started position reporting for device %s", self._device.id)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._cancel_pending_rearm()
        await self._async_request_reporting(0)
        _LOGGER.info("Stopped position reporting for device %s", self._device.id)

    async def _async_request_reporting(self, seconds: int) -> None:
        await self._send_confirmed_command(
            self._device.build_start_position_reporting_obj(seconds)
        )

    @callback
    def _schedule_rearm(self) -> None:
        self._cancel_pending_rearm()
        self._cancel_rearm = async_track_time_interval(
            self.hass,
            self._async_rearm,
            timedelta(seconds=POSITION_REPORTING_REARM_SECONDS),
        )

    @callback
    def _cancel_pending_rearm(self) -> None:
        if self._cancel_rearm is not None:
            self._cancel_rearm()
            self._cancel_rearm = None

    async def _async_rearm(self, _now: Any) -> None:
        try:
            await self._async_request_reporting(POSITION_REPORTING_SECONDS)
        except HomeAssistantError as err:
            # Stop re-requesting rather than hammering a gateway that rejects
            # the command. The switch follows the mower, so it turns itself off
            # once the running reporting session expires.
            self._cancel_pending_rearm()
            _LOGGER.warning(
                "Could not extend position reporting for device %s, stopping: %s",
                self._device.id,
                err,
            )


class GardenaScheduleDaySwitch(GardenaEntity, SwitchEntity):
    """Whether one of a schedule's weekdays is on.

    A schedule is a set of weekdays, and Home Assistant has no entity for a
    set — so each day is its own switch, which is also how it is read on a
    dashboard: seven switches, the ones that are on are the days it mows.
    """

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Device,
        index: int,
        day: str,
    ) -> None:
        super().__init__(coordinator, device)
        self._index = index
        self._day = day
        self._attr_unique_id = f"{device.id}_schedule_{index}_{day}"
        self._attr_translation_key = f"schedule_{day}"
        self._attr_translation_placeholders = {"number": str(index + 1)}

    def _schedule(self) -> bytes | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        raw = read_value(device, "lemonbeat", "schedule_config")
        return raw if isinstance(raw, bytes) else None

    @property
    def is_on(self) -> bool | None:
        raw = self._schedule()
        if raw is None:
            return None
        entries = describe_schedule(raw)
        if self._index >= len(entries):
            return None
        return self._day in entries[self._index]["days"]

    async def _async_set_day(self, enabled: bool) -> None:
        raw = self._schedule()
        if raw is None:
            return
        try:
            config = set_day(raw, self._index, self._day, enabled)
        except ValueError as err:
            # Turning off the last day would leave a schedule that never runs,
            # which the device has no way to express
            raise HomeAssistantError(str(err)) from err
        await self._send_confirmed_command(
            self._device.build_set_resource_obj(
                "lemonbeat", 0, "schedule_config", config
            )
        )
        _LOGGER.info(
            "Turned %s %s for schedule %s on device %s",
            self._day,
            "on" if enabled else "off",
            self._index + 1,
            self._device.id,
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set_day(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set_day(False)


class GardenaRunScheduleSwitch(GardenaEntity, SwitchEntity):
    """Whether the mower's schedule is allowed to run.

    Parking a mower is a state, not an errand: the device holds a "paused
    until" date, and docking writes one far in the future. So this is a
    switch — off parks the mower until further notice, on hands the schedule
    back — and it reads the device rather than remembering what was pressed,
    so parking from the mower or the app shows up here too.
    """

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_translation_key = "run_schedule"
    _attr_icon = "mdi:calendar-sync"

    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Device,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_run_schedule"

    @property
    def is_on(self) -> bool | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        paused = is_paused(read_value(device, "lemonbeat", "action_paused_until_1"))
        return None if paused is None else not paused

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._send_confirmed_command(
            self._device.build_set_resource_obj(
                "lemonbeat", 0, "action_paused_until_1", NOT_PAUSED
            )
        )
        _LOGGER.info("Let the schedule run again on device %s", self._device.id)

    async def async_turn_off(self, **kwargs: Any) -> None:
        # The dependency's own park: the same write docking does
        await self._send_confirmed_command(self._device.build_stop_mowing_obj())
        _LOGGER.info("Parked device %s until further notice", self._device.id)
