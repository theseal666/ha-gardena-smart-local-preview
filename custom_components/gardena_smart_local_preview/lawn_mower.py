# SPDX-FileCopyrightText: 2026 GARDENA GmbH
#
# SPDX-License-Identifier: Apache-2.0

"""GARDENA smart SILENO mower entity."""

from __future__ import annotations

import logging
from datetime import time as dt_time
from functools import partial

import voluptuous as vol
from gardena_smart_local_api.devices import Device, MowerState
from homeassistant.components.lawn_mower import (
    LawnMowerActivity,
    LawnMowerEntity,
    LawnMowerEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import GardenaSmartLocalCoordinator
from .device_data import has_resource, read_value
from .entity import (
    EntityFactories,
    GardenaEntity,
    async_setup_device_entities,
    get_mower_duration_hours,
)
from .schedules import (
    MAX_SCHEDULES,
    WEEKDAYS,
    add_entry,
    build_schedule,
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

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "start_mowing",
        {
            # Whole hours, matching the Default Mowing Duration number entity
            # and the range the GARDENA app offers for a manual start.
            vol.Optional("duration"): vol.All(vol.Coerce(int), vol.Range(min=1, max=6)),
            # Metres along the boundary wire to drive before starting to mow,
            # so a manual run can be sent to a far corner. Only mowers that
            # navigate report the resource this travels in; the upper bound is
            # the longest wire the model definitions describe.
            vol.Optional("distance"): vol.All(
                vol.Coerce(int), vol.Range(min=0, max=1000)
            ),
        },
        "async_start_mowing_for",
    )

    platform.async_register_entity_service(
        "set_schedule",
        {
            # The whole schedule, not a single entry: the device holds one
            # list and writing it replaces what was there, so a partial
            # update would quietly drop the entries it did not mention.
            vol.Required("schedules"): vol.All(
                [
                    {
                        vol.Required("days"): vol.All(
                            [vol.In(WEEKDAYS)], vol.Length(min=1)
                        ),
                        vol.Required("start"): cv.time,
                        vol.Required("duration_minutes"): vol.All(
                            vol.Coerce(int), vol.Range(min=1, max=60 * 24 * 7)
                        ),
                    }
                ],
                vol.Length(min=1, max=MAX_SCHEDULES),
            )
        },
        "async_set_schedule",
    )

    platform.async_register_entity_service(
        "add_schedule",
        {
            vol.Required("days"): vol.All([vol.In(WEEKDAYS)], vol.Length(min=1)),
            vol.Required("start"): cv.time,
            vol.Required("duration_minutes"): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=60 * 24 * 7)
            ),
        },
        "async_add_schedule",
    )
    platform.async_register_entity_service(
        "remove_schedule",
        {
            # Counted the way the entities are named, from one
            vol.Required("slot"): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=MAX_SCHEDULES)
            )
        },
        "async_remove_schedule",
    )

    def _entities_for_device(device: Device) -> EntityFactories:
        entities: EntityFactories = {}
        if hasattr(device, "build_start_mowing_obj"):
            entities["mower"] = partial(GardenaMower, coordinator, entry, device)
        return entities

    async_setup_device_entities(
        entry, coordinator, async_add_entities, _entities_for_device
    )


class GardenaMower(GardenaEntity, LawnMowerEntity):
    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        entry: ConfigEntry,
        device: Device,
    ) -> None:
        super().__init__(coordinator, device)
        self._entry = entry
        self._attr_unique_id = f"{device.id}_lawn_mower"
        self._attr_name = None
        self._attr_reports_position = False
        self._attr_supported_features = (
            LawnMowerEntityFeature.DOCK | LawnMowerEntityFeature.START_MOWING
        )
        if hasattr(device, "build_pause_mowing_obj"):
            self._attr_supported_features |= LawnMowerEntityFeature.PAUSE

    @property
    def activity(self) -> LawnMowerActivity | None:
        device = self.coordinator.data.get(self._device.id)
        if device is None:
            return None
        mower_state = device.state
        _LOGGER.debug("Mower status: %s", mower_state)
        match mower_state:
            case MowerState.CHARGING | MowerState.PARKED:
                return LawnMowerActivity.DOCKED

            case MowerState.LEAVING | MowerState.MOWING:
                return LawnMowerActivity.MOWING

            case MowerState.PAUSED:
                return LawnMowerActivity.PAUSED

            case MowerState.RETURNING:
                return LawnMowerActivity.RETURNING

            case MowerState.ERROR:
                return LawnMowerActivity.ERROR

        # MowerState.UNKNOWN or any state the dependency doesn't map yet.
        return None

    async def async_start_mowing(self) -> None:
        await self.async_start_mowing_for()

    async def async_start_mowing_for(
        self, duration: int | None = None, distance: int | None = None
    ) -> None:
        hours = (
            duration
            if duration is not None
            else get_mower_duration_hours(self._entry, self._device.id)
        )
        if distance:
            if not has_resource(self._device, "lemonbeat", "mower_timer_with_distance"):
                raise HomeAssistantError(
                    f"Device {self._device.id} cannot start a given distance from "
                    f"its charging station"
                )
            request = self._device.build_start_mowing_obj(hours * 3600, distance)
        else:
            request = self._device.build_start_mowing_obj(hours * 3600)
        await self._send_confirmed_command(request)
        _LOGGER.info(
            "Start mowing with %s for %s hours, %s m from the charging station",
            self._device.id,
            hours,
            distance or 0,
        )

    async def async_set_schedule(self, schedules: list[dict]) -> None:
        if not has_resource(self._device, "lemonbeat", "schedule_config"):
            raise HomeAssistantError(
                f"Device {self._device.id} does not hold a schedule this "
                f"integration can write"
            )
        # Written back per slot, so the byte the device keeps in each entry
        # survives a schedule this integration did not write
        held = read_value(self._device, "lemonbeat", "schedule_config")
        try:
            config = build_schedule(
                [
                    {
                        "days": entry["days"],
                        "start": entry["start"].strftime("%H:%M"),
                        "duration_minutes": entry["duration_minutes"],
                    }
                    for entry in schedules
                ],
                template=held if isinstance(held, bytes) else None,
            )
        except ValueError as err:
            raise HomeAssistantError(f"Invalid schedule: {err}") from err

        await self._send_confirmed_command(
            self._device.build_set_resource_obj(
                "lemonbeat", 0, "schedule_config", config
            )
        )
        _LOGGER.info(
            "Wrote %s schedule(s) to device %s", len(schedules), self._device.id
        )

    def _held_schedule(self) -> bytes | None:
        if not has_resource(self._device, "lemonbeat", "schedule_config"):
            raise HomeAssistantError(
                f"Device {self._device.id} does not hold a schedule this "
                f"integration can write"
            )
        held = read_value(self._device, "lemonbeat", "schedule_config")
        return held if isinstance(held, bytes) else None

    async def _async_write_schedule(self, config: bytes) -> None:
        await self._send_confirmed_command(
            self._device.build_set_resource_obj(
                "lemonbeat", 0, "schedule_config", config
            )
        )

    async def async_add_schedule(
        self, days: list[str], start: dt_time, duration_minutes: int
    ) -> None:
        try:
            config = add_entry(
                self._held_schedule(),
                {
                    "days": days,
                    "start": start.strftime("%H:%M"),
                    "duration_minutes": duration_minutes,
                },
            )
        except ValueError as err:
            raise HomeAssistantError(f"Invalid schedule: {err}") from err

        await self._async_write_schedule(config)
        _LOGGER.info("Added a schedule to device %s", self._device.id)

    async def async_remove_schedule(self, slot: int) -> None:
        held = self._held_schedule()
        if held is None:
            raise HomeAssistantError(f"Device {self._device.id} holds no schedule")
        try:
            config = remove_entry(held, slot - 1)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

        await self._async_write_schedule(config)
        _LOGGER.info("Removed schedule %s from device %s", slot, self._device.id)

    async def async_dock(self) -> None:
        await self._send_confirmed_command(self._device.build_stop_mowing_obj())
        _LOGGER.info("Stop mowing with %s", self._device.id)

    async def async_pause(self) -> None:
        if hasattr(self._device, "build_pause_mowing_obj"):
            await self._send_confirmed_command(self._device.build_pause_mowing_obj())
            _LOGGER.info("Pause mowing with %s", self._device.id)
        else:
            _LOGGER.warning("Pause not supported for device %s", self._device.id)
