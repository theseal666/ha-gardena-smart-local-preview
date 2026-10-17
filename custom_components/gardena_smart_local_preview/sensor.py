# SPDX-FileCopyrightText: 2026 GARDENA GmbH
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime
from functools import partial
from typing import Any, ClassVar

from gardena_smart_local_api.devices import Pump
from gardena_smart_local_api.devices.device import Device, FirmwareUpdateState
from gardena_smart_local_api.devices.irrigation import PumpState
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    LIGHT_LUX,
    PERCENTAGE,
    EntityCategory,
    UnitOfLength,
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
    UnitOfVolumeFlowRate,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import GardenaSmartLocalCoordinator
from .device_data import (
    has_resource,
    read_int,
    read_int_list,
    read_local_timestamp,
    read_reported_at,
    read_value,
)
from .entity import EntityFactories, GardenaEntity, async_setup_device_entities
from .error_codes import error_name, error_names
from .schedules import describe_schedule

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
        if hasattr(device, "temperature"):
            entities["temperature"] = partial(
                GardenaTemperatureSensor, coordinator, device
            )
        if hasattr(device, "soil_moisture"):
            entities["soil_moisture"] = partial(
                GardenaSoilMoistureSensor, coordinator, device
            )
        if hasattr(device, "light"):
            entities["light"] = partial(GardenaLightSensor, coordinator, device)
        if hasattr(device, "battery_level"):
            entities["battery"] = partial(GardenaBatterySensor, coordinator, device)
        if hasattr(device, "rf_link_quality"):
            entities["rf_link_quality"] = partial(
                GardenaRfLinkQualitySensor, coordinator, device
            )
        if isinstance(device, Pump):
            entities["pump_pressure"] = partial(
                GardenaPumpPressureSensor, coordinator, device
            )
            entities["pump_temperature"] = partial(
                GardenaPumpTemperatureSensor, coordinator, device
            )
            entities["pump_flow_rate"] = partial(
                GardenaPumpFlowRateSensor, coordinator, device
            )
            entities["pump_flow_total"] = partial(
                GardenaPumpFlowTotalSensor, coordinator, device
            )
            entities["pump_flow_since_reset"] = partial(
                GardenaPumpFlowSinceResetSensor, coordinator, device
            )
            entities["pump_state"] = partial(
                GardenaPumpStateSensor, coordinator, device
            )
        if hasattr(device, "schedule_count"):
            entities["schedule_count"] = partial(
                GardenaScheduleCountSensor, coordinator, device
            )
        if has_resource(device, "lemonbeat", "schedule_config"):
            entities["schedule"] = partial(GardenaScheduleSensor, coordinator, device)
        for key, factory in COUNTER_SENSORS.items():
            if has_resource(device, "lemonbeat", key):
                entities[key] = partial(factory, coordinator, device)
        if has_resource(device, "lemonbeat", "guide_wire_length"):
            entities["guide_wire_length"] = partial(
                GardenaGuideWireLengthSensor, coordinator, device
            )
        if has_resource(device, "lemonbeat", "timestamp_next_start"):
            entities["next_start"] = partial(
                GardenaNextStartSensor, coordinator, device
            )
        if has_resource(device, "lemonbeat", "source_for_next_start"):
            entities["next_start_source"] = partial(
                GardenaNextStartSourceSensor, coordinator, device
            )
        if has_resource(device, "device", "error_code"):
            entities["error_code"] = partial(
                GardenaErrorCodeSensor, coordinator, device
            )
        if has_resource(device, "lemonbeat", "last_error_code"):
            entities["last_error"] = partial(
                GardenaLastErrorSensor, coordinator, device
            )
            entities["last_error_code"] = partial(
                GardenaLastErrorCodeSensor, coordinator, device
            )
        if has_resource(device, "lemonbeat", "timestamp_last_error_code"):
            entities["last_error_time"] = partial(
                GardenaLastErrorTimeSensor, coordinator, device
            )
        if has_resource(device, "mower_app", "error"):
            entities["mower_error_code"] = partial(
                GardenaMowerErrorCodeSensor, coordinator, device
            )
        if has_resource(device, "lemonbeat_status_message", "code"):
            entities["status_message_code"] = partial(
                GardenaStatusMessageCodeSensor, coordinator, device
            )
        entities["firmware_update_state"] = partial(
            GardenaFirmwareUpdateStateSensor, coordinator, device
        )
        return entities

    async_setup_device_entities(
        entry, coordinator, async_add_entities, _entities_for_device
    )


class GardenaTemperatureSensor(GardenaEntity, SensorEntity):
    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Device,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_temperature"
        self._attr_translation_key = "temperature"
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    @property
    def native_value(self) -> float | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        temp = device.temperature
        return float(temp) if temp is not None else None


class GardenaSoilMoistureSensor(GardenaEntity, SensorEntity):
    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Device,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_soil_moisture"
        self._attr_translation_key = "soil_moisture"
        self._attr_device_class = SensorDeviceClass.MOISTURE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = PERCENTAGE

    @property
    def native_value(self) -> float | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        moisture = device.soil_moisture
        return float(moisture) if moisture is not None else None


class GardenaLightSensor(GardenaEntity, SensorEntity):
    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Device,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_light"
        self._attr_translation_key = "light"
        self._attr_device_class = SensorDeviceClass.ILLUMINANCE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = LIGHT_LUX

    @property
    def native_value(self) -> float | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        lux = device.light
        return float(lux) if lux is not None else None


class GardenaBatterySensor(GardenaEntity, SensorEntity):
    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Device,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_battery"
        self._attr_translation_key = "battery"
        self._attr_device_class = SensorDeviceClass.BATTERY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = PERCENTAGE

    @property
    def native_value(self) -> float | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        level = device.battery_level
        return float(level) if level is not None else None


class GardenaRfLinkQualitySensor(GardenaEntity, SensorEntity):
    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Device,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_rf_link_quality"
        self._attr_translation_key = "rf_link_quality"
        self._attr_icon = "mdi:signal"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> int | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        return device.rf_link_quality


class GardenaPumpPressureSensor(GardenaEntity, SensorEntity):
    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Pump,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_outlet_pressure"
        self._attr_translation_key = "outlet_pressure"
        self._attr_device_class = SensorDeviceClass.PRESSURE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = UnitOfPressure.BAR

    @property
    def native_value(self) -> float | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        return device.outlet_pressure


class GardenaPumpTemperatureSensor(GardenaEntity, SensorEntity):
    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Pump,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_outlet_temperature"
        self._attr_translation_key = "outlet_temperature"
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    @property
    def native_value(self) -> float | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        temp = device.outlet_temperature
        return float(temp) if temp is not None else None


class GardenaPumpFlowRateSensor(GardenaEntity, SensorEntity):
    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Pump,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_flow_rate"
        self._attr_translation_key = "flow_rate"
        self._attr_device_class = SensorDeviceClass.VOLUME_FLOW_RATE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = UnitOfVolumeFlowRate.LITERS_PER_HOUR

    @property
    def native_value(self) -> float | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        rate = device.flow_rate
        return float(rate) if rate is not None else None


class GardenaPumpFlowTotalSensor(GardenaEntity, SensorEntity):
    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Pump,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_flow_total"
        self._attr_translation_key = "total_flow"
        self._attr_device_class = SensorDeviceClass.WATER
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS

    @property
    def native_value(self) -> float | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        total = device.flow_total
        return float(total) if total is not None else None


class GardenaPumpFlowSinceResetSensor(GardenaEntity, SensorEntity):
    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Pump,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_flow_since_reset"
        self._attr_translation_key = "flow_since_reset"
        self._attr_device_class = SensorDeviceClass.WATER
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS

    @property
    def native_value(self) -> float | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        flow = device.flow_since_last_reset
        return float(flow) if flow is not None else None


class GardenaPumpStateSensor(GardenaEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options: ClassVar = [str(state) for state in PumpState]

    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Pump,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_pump_state"
        self._attr_translation_key = "pump_state"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> str | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        state = device.pump_state
        return str(state) if state is not None else None


class GardenaScheduleCountSensor(GardenaEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "schedule_count"
    _attr_icon = "mdi:calendar-check"

    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Device,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_schedule_count"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> int | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        return device.schedule_count


class GardenaFirmwareUpdateStateSensor(GardenaEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options: ClassVar = [str(state) for state in FirmwareUpdateState]

    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Device,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_firmware_update_state"
        self._attr_translation_key = "firmware_update_state"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self.coordinator.async_refresh_firmware(self._device.id)

    @property
    def native_value(self) -> str | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        state = device.firmware_update_state
        return str(state) if state is not None else None


# The devices report errors as bare numbers. The GARDENA app resolves them to
# text from a table that is not part of the local API, so the codes stay
# numeric here instead of being mapped to invented names.
class GardenaErrorCodeSensor(GardenaEntity, SensorEntity):
    """Error code(s) the device currently reports.

    This is the standard device error resource every GARDENA smart device
    carries, not the mower-specific one.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "error_code"
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Device,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_error_code"

    def _codes(self) -> list[int] | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        return read_int_list(device, "device", "error_code")

    @property
    def native_value(self) -> int | None:
        codes = self._codes()
        if codes is None:
            return None
        # The device keeps a 0 ("no error") entry in the list and reports real
        # errors alongside it, so the first non-zero code is the current one.
        return next((code for code in codes if code), 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        codes = self._codes()
        if codes is None:
            return None
        device = self.coordinator.data.get(self._device.id)
        return {
            # Several codes can be active at once, and only the first one shows
            # up as the state.
            "error_codes": codes,
            "reported_at": read_reported_at(device, "device", "error_code")
            if device
            else None,
        }


class GardenaLastErrorSensor(GardenaEntity, SensorEntity):
    """The last error a mower reported, by name.

    The numeric code stays available both as an attribute and as its own
    sensor: it is what an automation can act on for an error whose name is not
    known yet, and what to quote when asking what a code means.
    """

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options: ClassVar = error_names()
    _attr_translation_key = "last_error"
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Device,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_last_error"

    def _code(self) -> int | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        return read_int(device, "lemonbeat", "last_error_code")

    @property
    def native_value(self) -> str | None:
        code = self._code()
        return None if code is None else error_name(code)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        code = self._code()
        if code is None:
            return None
        device = self.coordinator.data.get(self._device.id)
        return {
            "code": code,
            "reported_at": read_reported_at(device, "lemonbeat", "last_error_code")
            if device
            else None,
        }


class GardenaLastErrorCodeSensor(GardenaEntity, SensorEntity):
    """Last error code a mower reported, kept after the error is cleared."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "last_error_code"
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Device,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_last_error_code"

    @property
    def native_value(self) -> int | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        return read_int(device, "lemonbeat", "last_error_code")


class GardenaLastErrorTimeSensor(GardenaEntity, SensorEntity):
    """When the mower reported its last error."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "last_error_time"

    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Device,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_last_error_time"

    @property
    def native_value(self) -> datetime | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        return read_local_timestamp(device, "lemonbeat", "timestamp_last_error_code")


class GardenaMowerErrorCodeSensor(GardenaEntity, SensorEntity):
    """Error code of a Gen2 mower's mower application."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "mower_error_code"
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Device,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_mower_error_code"

    @property
    def native_value(self) -> int | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        return read_int(device, "mower_app", "error")

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        confirmable = read_value(device, "mower_app", "is_error_confirmable")
        return {
            # Whether the error can be acknowledged remotely at all, or whether
            # the mower has to be attended to in the garden.
            "confirmable": None if confirmable is None else bool(confirmable),
            "reported_at": read_reported_at(device, "mower_app", "error"),
        }


class GardenaStatusMessageCodeSensor(GardenaEntity, SensorEntity):
    """Code of the device's last status message.

    The message is the device's own log line (level, type and four payload
    bytes), which carries more detail about a problem than the error code
    alone. Off by default because the stream is mostly informational.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "status_message_code"
    _attr_icon = "mdi:message-alert-outline"

    # Taken from the model definition's description of the level resource.
    _LEVELS: ClassVar = {
        0: "disabled",
        1: "important",
        2: "error",
        3: "warning",
        4: "info",
        5: "debug",
    }

    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Device,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_status_message_code"

    @property
    def native_value(self) -> int | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        return read_int(device, "lemonbeat_status_message", "code")

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        level = read_int(device, "lemonbeat_status_message", "level")
        data = read_value(device, "lemonbeat_status_message", "data")
        return {
            "level": self._LEVELS.get(level, level),
            "message_type": read_int(device, "lemonbeat_status_message", "type"),
            "data": data if isinstance(data, str) else None,
            # A status message is a log line, so when it arrived is most of its
            # meaning: an `error` level from last week is not a current fault.
            "reported_at": read_reported_at(device, "lemonbeat_status_message", "code"),
        }


class _GardenaCounterSensor(GardenaEntity, SensorEntity):
    """A counter the device keeps and only ever increases."""

    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _resource: ClassVar[str] = ""

    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Device,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_{self._resource}"
        self._attr_translation_key = self._resource

    @property
    def native_value(self) -> int | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        return read_int(device, "lemonbeat", self._resource)


class GardenaCuttingTimeSensor(_GardenaCounterSensor):
    """Hours the cutting disc has run."""

    _resource = "cutting_time"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_icon = "mdi:saw-blade"


class GardenaRunningTimeSensor(_GardenaCounterSensor):
    """Hours the wheel motors have run."""

    _resource = "running_time"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_icon = "mdi:timer-play-outline"


class GardenaChargingCyclesSensor(_GardenaCounterSensor):
    """Completed charging cycles, which is what wears the battery out."""

    _resource = "charging_cycles"
    _attr_icon = "mdi:battery-sync-outline"


class GardenaCollisionsSensor(_GardenaCounterSensor):
    """Collisions counted by the mower."""

    _resource = "collisions"
    _attr_icon = "mdi:car-brake-alert"


class GardenaGuideWireLengthSensor(GardenaEntity, SensorEntity):
    """Length of the guide wire, as last measured by the mower."""

    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_native_unit_of_measurement = UnitOfLength.METERS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "guide_wire_length"
    _attr_icon = "mdi:cable-data"

    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Device,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_guide_wire_length"

    @property
    def native_value(self) -> int | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        length = read_int(device, "lemonbeat", "guide_wire_length")
        # The model definition calls 0 uninitialised, not a wire of zero metres
        return length or None


class GardenaNextStartSensor(GardenaEntity, SensorEntity):
    """When the mower is next due to start on its own."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "next_start"
    _attr_icon = "mdi:clock-start"

    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Device,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_next_start"

    @property
    def native_value(self) -> datetime | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        # Zero means "no start planned", which read_local_timestamp returns as
        # None — the same thing a parked mower reports.
        return read_local_timestamp(device, "lemonbeat", "timestamp_next_start")


class GardenaNextStartSourceSensor(GardenaEntity, SensorEntity):
    """What is going to start the mower next."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "next_start_source"
    _attr_icon = "mdi:help-rhombus-outline"

    # Taken from the model definition's description of the resource
    _SOURCES: ClassVar = {
        0: "no_source",
        1: "daily_limit",
        2: "week_timer",
        3: "countdown",
        4: "charging",
        5: "auto_timer",
        6: "frost",
    }
    _attr_options: ClassVar = [*_SOURCES.values(), "unknown"]

    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Device,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_next_start_source"

    @property
    def native_value(self) -> str | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        source = read_int(device, "lemonbeat", "source_for_next_start")
        if source is None:
            return None
        return self._SOURCES.get(source, "unknown")


COUNTER_SENSORS: dict[str, type[_GardenaCounterSensor]] = {
    "cutting_time": GardenaCuttingTimeSensor,
    "running_time": GardenaRunningTimeSensor,
    "charging_cycles": GardenaChargingCyclesSensor,
    "collisions": GardenaCollisionsSensor,
}


class GardenaScheduleSensor(GardenaEntity, SensorEntity):
    """The schedule the device is running, as the device holds it.

    The state is how many entries there are; the entries themselves are
    attributes, because a schedule is a list and a state is a string. Set a
    new one with the `set_schedule` action, or empty it with the clear
    schedules button.
    """

    _attr_translation_key = "schedule"
    _attr_icon = "mdi:calendar-clock"

    def __init__(
        self,
        coordinator: GardenaSmartLocalCoordinator,
        device: Device,
    ) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.id}_schedule"

    def _entries(self) -> list[dict[str, Any]] | None:
        device = self.coordinator.data.get(self._device.id)
        if not device:
            return None
        raw = read_value(device, "lemonbeat", "schedule_config")
        if not isinstance(raw, bytes):
            return None
        return describe_schedule(raw)

    @property
    def native_value(self) -> int | None:
        entries = self._entries()
        return None if entries is None else len(entries)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        entries = self._entries()
        return None if entries is None else {"schedules": entries}
