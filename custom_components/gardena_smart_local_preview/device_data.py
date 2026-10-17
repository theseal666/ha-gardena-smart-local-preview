# SPDX-FileCopyrightText: 2026 GARDENA GmbH
#
# SPDX-License-Identifier: Apache-2.0

"""Reads for resources the dependency does not wrap in a typed property yet.

gardena-smart-local-api exposes typed properties for most resources, but the
error-code resources of a mower are only in the model definitions. The helpers
here resolve them through the device's own model definition, so an entity is
only created for a model that actually declares the resource instead of
guessing from the device class.
"""

from __future__ import annotations

import struct
from datetime import datetime

from gardena_smart_local_api.devices.device import Device
from gardena_smart_local_api.resources import VALUE_TYPES, IpsoPath
from homeassistant.util import dt as dt_util


def has_resource(device: Device, object_name: str, resource_name: str) -> bool:
    """Return True if the device's model declares the resource."""
    ipso_object = device.model_definition.objects.get(object_name)
    if not isinstance(ipso_object, dict):
        return False
    resources = ipso_object.get("resources")
    return isinstance(resources, dict) and resource_name in resources


def read_value(
    device: Device,
    object_name: str,
    resource_name: str,
    instance_id: str = "0",
) -> VALUE_TYPES | None:
    """Return the last reported value of a resource, or None if unreported."""
    return device.get_value(
        IpsoPath(
            object_name=object_name,
            object_instance_id=instance_id,
            resource_name=resource_name,
        )
    )


def read_int(
    device: Device,
    object_name: str,
    resource_name: str,
    instance_id: str = "0",
) -> int | None:
    """Return an integer resource, or None if unreported or another type."""
    value = read_value(device, object_name, resource_name, instance_id)
    # bool is an int subclass, and a boolean resource is never a code or count
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def read_int_list(
    device: Device,
    object_name: str,
    resource_name: str,
    instance_id: str = "0",
) -> list[int] | None:
    """Return an integer-array resource, or None if unreported."""
    value = read_value(device, object_name, resource_name, instance_id)
    if isinstance(value, list) and all(isinstance(item, int) for item in value):
        return value
    return None


def read_reported_at(
    device: Device,
    object_name: str,
    resource_name: str,
    instance_id: str = "0",
) -> datetime | None:
    """Return when the gateway last reported a value for the resource.

    Every reported value carries the gateway's own timestamp, which is what
    tells a current fault from one that cleared days ago — the value alone
    cannot, since the gateway keeps reporting the last one it saw.
    """
    field = device.get_field(
        IpsoPath(
            object_name=object_name,
            object_instance_id=instance_id,
            resource_name=resource_name,
        )
    )
    if field is None or field.ts is None:
        return None
    return dt_util.utc_from_timestamp(field.ts)


def read_local_timestamp(
    device: Device,
    object_name: str,
    resource_name: str,
    instance_id: str = "0",
) -> datetime | None:
    """Return a timestamp resource as an aware UTC datetime.

    The device reports these as four big-endian bytes counting seconds since
    1970-01-01 in *local* time, so the raw number is read as a wall-clock time
    in Home Assistant's time zone rather than as a UTC epoch. A zero means the
    event the timestamp belongs to never happened.
    """
    raw = read_value(device, object_name, resource_name, instance_id)
    if not isinstance(raw, bytes) or len(raw) != 4:
        return None
    (seconds,) = struct.unpack(">I", raw)
    if seconds == 0:
        return None
    naive = datetime.fromtimestamp(seconds, tz=dt_util.UTC).replace(tzinfo=None)
    return dt_util.as_utc(naive)
