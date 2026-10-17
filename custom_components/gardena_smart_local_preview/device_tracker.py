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
from homeassistant.util.location import distance

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


# Both fixes of one frame are taken in the same garden, which is tens of
# metres across, so a disagreement far beyond that means the LONA fix is not
# from this garden at all: a mower that has changed gardens keeps reporting the
# previous one's coordinates, with its ready flag set, until it has mown the
# new garden. Observed on a second-hand 53988 reporting a LONA fix 25 km away
# from its own GNSS fix.
MAX_FIX_DISAGREEMENT_M = 150


class GardenaMowerTracker(GardenaEntity, TrackerEntity):
    """A mower's last reported position.

    A mower with LONA reports two fixes in one frame: the LONA one it
    navigates by, and the raw GNSS one. The LONA fix is the more precise of
    the two and is used when the frame says it is ready and the two agree;
    otherwise the GNSS fix is used. Both fixes stay available as attributes,
    along with the heading and the compass.
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
    def _fix(self) -> tuple[str, float, float] | None:
        """Return the fix to report as (source, latitude, longitude)."""
        position = self._position
        if position is None:
            return None

        lona = _coordinates(position.latitude, position.longitude)
        # Only a mower with LONA reports a second fix; for every other one the
        # single pair above is the GNSS fix itself.
        if not hasattr(position, "gnss_latitude"):
            return ("gnss", *lona) if lona else None

        gnss = _coordinates(position.gnss_latitude, position.gnss_longitude)
        if lona is None:
            return ("gnss", *gnss) if gnss else None
        if gnss is None:
            # Nothing to cross-check against, so the mower is taken at its word
            return ("lona", *lona)
        if not position.lona_is_ready:
            return ("gnss", *gnss)
        disagreement = distance(*lona, *gnss)
        if disagreement is not None and disagreement > MAX_FIX_DISAGREEMENT_M:
            return ("gnss", *gnss)
        return ("lona", *lona)

    @property
    def latitude(self) -> float | None:
        fix = self._fix
        return fix[1] if fix else None

    @property
    def longitude(self) -> float | None:
        fix = self._fix
        return fix[2] if fix else None

    # location_accuracy is deliberately not set from the frame's accuracy
    # field: Home Assistant draws it as a radius in metres, and the unit the
    # mower reports it in is undocumented (a mower sitting in its charging
    # station reports 1104, which is not metres). The raw figure is kept as an
    # attribute instead of being turned into a kilometre-wide circle.

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        position = self._position
        if position is None:
            return None
        fix = self._fix
        attributes: dict[str, Any] = {
            # Which fix the state is based on
            "fix_source": fix[0] if fix else None,
            # Heading, the raw GNSS fix, its accuracy figure and the compass
            **position.model_dump(exclude={"latitude", "longitude"}),
        }
        if hasattr(position, "gnss_latitude"):
            # The LONA fix stays visible even when the state uses the GNSS one
            attributes["lona_latitude"] = position.latitude or None
            attributes["lona_longitude"] = position.longitude or None
        return attributes


def _coordinates(latitude: float, longitude: float) -> tuple[float, float] | None:
    """Return the pair, or None for the zeroes of an unset fix."""
    if not latitude and not longitude:
        return None
    return latitude, longitude
