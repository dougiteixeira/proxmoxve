# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Sensor to read Proxmox VE data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import homeassistant.util.dt as dt_util
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    REVOLUTIONS_PER_MINUTE,
    EntityCategory,
    Platform,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfFrequency,
    UnitOfInformation,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.helpers.typing import UNDEFINED, StateType

from . import async_migrate_old_unique_ids, device_info
from .const import (
    CONF_LXC,
    CONF_NODES,
    CONF_QEMU,
    CONF_STORAGE,
    COORDINATORS,
    ProxmoxKeyAPIParse,
    ProxmoxType,
)
from .entity import ProxmoxEntity, ProxmoxEntityDescription

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.device_registry import DeviceInfo
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
    from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

    from .models import ProxmoxDiskData, ProxmoxZFSData

CHIP_DEVICE_MAP: Final[dict[str, str]] = {
    "k10temp": "CPU",
    "k8temp": "CPU",
    "coretemp": "CPU",
    "peci-cputemp": "CPU",
    "zenpower": "CPU",
    "fam15h": "CPU",
    "sbtsi": "CPU",
    "sbrmi": "CPU",
    "amdgpu": "GPU",
    "i915": "GPU",
    "nvidia_gpu": "GPU",
    "nvme": "NVMe",
    "drivetemp": "Drive",
    "jc42": "Memory",
    "spd5118": "Memory",
    "peci-dimmtemp": "Memory",
    "sodimm": "Memory",
    "tmp102": "Memory",
    "tmp103": "Memory",
    "tmp401": "Memory",
    "tmp421": "Memory",
    "lm75": "Memory",
    "lm90": "Memory",
    "adm1021": "Memory",
    "max6642": "Memory",
    "lm95234": "Memory",
    "nct6775": "Motherboard",
    "nct6683": "Motherboard",
    "nct6106": "Motherboard",
    "it87": "Motherboard",
    "w83627": "Motherboard",
    "w83667": "Motherboard",
    "f71882": "Motherboard",
    "asus_ec": "Motherboard",
    "mlx5": "NIC",
    "igb": "NIC",
    "ixgbe": "NIC",
    "acpitz": "Motherboard",
    "dell_smm": "Laptop",
    "macsmc": "Laptop",
    "thinkpad": "Laptop",
    "lm25066": "PSU",
    "lm5066": "PSU",
    "pmbus": "PSU",
    "corsair": "PSU",
    "ibm-cffps": "PSU",
    "emc2305": "Cooling",
    "max31785": "Cooling",
    "pwm-fan": "Cooling",
    "g760a": "Cooling",
    "pc87360": "Cooling",
    "raspberrypi": "SoC",
    "i5500": "Chipset",
    "i5k_amb": "Chipset",
}

SENSOR_LABEL_MAP: Final[dict[str, dict[str, str]]] = {
    "amdgpu": {
        "edge": "GPU hotspot",
        "junction": "GPU junction",
        "mem": "GPU memory temperature",
        "vddgfx": "GPU core voltage",
        "vddnb": "GPU SoC voltage",
        "sclk": "GPU shader clock",
        "mclk": "GPU memory clock",
        "ppt": "GPU package power",
    },
    "k10temp": {
        "tctl": "CPU control temperature",
        "tdie": "CPU die temperature",
        "tccd1": "CCD 1 temperature",
        "tccd2": "CCD 2 temperature",
        "tccd3": "CCD 3 temperature",
        "tccd4": "CCD 4 temperature",
        "tccd5": "CCD 5 temperature",
        "tccd6": "CCD 6 temperature",
        "tccd7": "CCD 7 temperature",
        "tccd8": "CCD 8 temperature",
    },
    "k8temp": {
        "temp1": "CPU temperature",
    },
    "coretemp": {
        "package id 0": "CPU package temperature",
    },
    "i915": {
        "temp1": "GPU temperature",
        "power1": "GPU power",
    },
    "nvidia_gpu": {
        "temp1": "GPU temperature",
        "power1": "GPU power",
        "fan1": "GPU fan",
    },
    "nvme": {
        "composite": "NVMe temperature",
        "sensor 1": "NVMe sensor 1",
        "sensor 2": "NVMe sensor 2",
        "sensor 3": "NVMe sensor 3",
        "sensor 4": "NVMe sensor 4",
        "sensor 5": "NVMe sensor 5",
    },
    "drivetemp": {
        "temp1": "Drive temperature",
    },
    "jc42": {
        "temp1": "Memory module temperature",
    },
    "spd5118": {
        "temp1": "DDR5 temperature",
    },
    "mlx5": {
        "temp1": "NIC temperature",
        "temp2": "NIC ambient temperature",
        "temp3": "NIC internal temperature",
        "power1": "NIC power",
    },
    "acpitz": {
        "temp1": "ACPI zone temperature",
    },
    "fam15h": {
        "power1": "CPU package power",
        "power1_average": "CPU average power",
    },
    "peci-cputemp": {
        "die": "CPU package die temperature",
        "dts": "CPU DTS temperature",
        "tcontrol": "CPU target temperature",
        "tthrottle": "CPU throttling temperature",
    },
    "dell_smm": {
        "temp1": "CPU temperature",
        "temp2": "GPU temperature",
        "temp3": "SODIMM temperature",
    },
    "sbtsi": {
        "temp1": "SoC temperature",
    },
    "nct6775": {
        "systin": "System temperature",
        "cputin": "CPU temperature",
        "auxtin": "Auxiliary temperature",
    },
    "macsmc": {
        "temp1": "SMC temperature",
    },
    "pmbus": {
        "temp1": "PSU temperature",
        "temp2": "PSU temperature 2",
        "fan1": "PSU fan",
        "power1": "PSU input power",
        "power2": "PSU output power",
    },
}

DEVICE_ICONS: Final[dict[str, str]] = {
    "CPU": "mdi:cpu-64-bit",
    "GPU": "mdi:gpu",
    "NVMe": "mdi:harddisk",
    "Drive": "mdi:harddisk",
    "Memory": "mdi:memory",
    "Motherboard": "mdi:chip",
    "NIC": "mdi:network-switch",
    "Laptop": "mdi:laptop",
    "PSU": "mdi:power-plug",
    "Cooling": "mdi:fan",
    "SoC": "mdi:chip",
    "Chipset": "mdi:chip",
}


def _get_chip_prefix(chip: str) -> str:
    """Extract the chip prefix from a full chip identifier for map lookup."""
    for prefix in CHIP_DEVICE_MAP:
        if chip.startswith(prefix):
            return prefix
    fallback = (
        chip.split("-", maxsplit=1)[0]
        if "-" in chip
        else chip.split(" ", maxsplit=1)[0]
    )
    return fallback.lower()


def _classify_sensor_key(sensor_key: str) -> dict:
    """Classify a sensor key to determine device type, unit, and display name."""
    parts = sensor_key.rsplit(" ", 1)
    chip = parts[0].lower()
    sensor = parts[1] if len(parts) > 1 else ""
    sensor_lower = sensor.lower()

    chip_prefix = _get_chip_prefix(chip)
    device_type = CHIP_DEVICE_MAP.get(
        chip_prefix, chip_prefix.capitalize() or "Unknown"
    )

    chip_labels = SENSOR_LABEL_MAP.get(chip_prefix, {})
    known_label = None
    for key, label in chip_labels.items():
        if sensor_lower == key or sensor_lower.startswith(key.rstrip("*")):
            known_label = label
            break

    if sensor_lower.startswith(("vdd", "vcore", "in", "_in")):
        return {
            "name": known_label or f"{device_type} voltage",
            "native_unit": UnitOfElectricPotential.VOLT,
            "device_class": SensorDeviceClass.VOLTAGE,
            "icon": "mdi:flash",
            "conversion_fn": None,
            "suggested_precision": 3,
        }

    if sensor_lower in ("ppt", "ppt1") or sensor_lower.startswith("power"):
        return {
            "name": known_label or f"{device_type} power",
            "native_unit": UnitOfPower.WATT,
            "device_class": SensorDeviceClass.POWER,
            "icon": "mdi:flash-outline",
            "conversion_fn": None,
            "suggested_precision": 1,
        }

    if sensor_lower in ("sclk", "mclk", "freq1", "freq2"):
        return {
            "name": known_label or f"{device_type} clock",
            "native_unit": UnitOfFrequency.MEGAHERTZ,
            "device_class": SensorDeviceClass.FREQUENCY,
            "icon": "mdi:speedometer",
            "conversion_fn": lambda x: x / 1_000_000,
            "suggested_precision": 0,
        }

    if sensor_lower.startswith("fan"):
        return {
            "name": known_label or f"{device_type} {sensor}".title(),
            "native_unit": REVOLUTIONS_PER_MINUTE,
            "device_class": None,
            "icon": "mdi:fan",
            "conversion_fn": None,
            "suggested_precision": 0,
        }

    if sensor_lower.startswith("curr"):
        return {
            "name": known_label or f"{device_type} current",
            "native_unit": UnitOfElectricCurrent.AMPERE,
            "device_class": SensorDeviceClass.CURRENT,
            "icon": "mdi:current-ac",
            "conversion_fn": None,
            "suggested_precision": 2,
        }

    return {
        "name": known_label or f"{device_type} {sensor}",
        "native_unit": UnitOfTemperature.CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
        "icon": "mdi:thermometer",
        "conversion_fn": None,
        "suggested_precision": 1,
    }


@dataclass(frozen=True, kw_only=True)
class ProxmoxSensorEntityDescription(ProxmoxEntityDescription, SensorEntityDescription):
    """Class describing Proxmox sensor entities."""

    conversion_fn: Callable | None = None  # conversion factor to be applied to units
    value_fn: Callable[[Any], Any | str] | None = None
    api_category: ProxmoxType | None = (
        None  # Set when the sensor applies to only QEMU or LXC, if None applies to both.
    )
    extra_attrs: list[str] | None = None
    # For timestamps derived from a counter (e.g. a boot time computed from an
    # uptime): keep reporting the previous value while the new one is within
    # this margin of it, so rounding noise is not recorded as a state change.
    stable_within: timedelta | None = None


def percentage_or_unknown(value: float | UndefinedType | None) -> float | None:
    """
    Turn a 0..1 ratio into a percentage, keeping "unknown" unknown.

    A sensor that reports 0% when it simply has no reading looks like a
    measurement, which is worse than reporting nothing: 0% disk used and "I
    cannot see inside this guest" are very different statements.

    The result is capped at 100%. A QEMU guest whose balloon driver reports
    no statistics leaves Proxmox with only the host-side size of the QEMU
    process, which carries emulator overhead and can sit above the memory
    the guest was configured with - that is how a "memory used percentage"
    of 106% reached a dashboard. Above the cap the ratio has stopped
    describing how full the guest is, and 100% is the closest true thing to
    say about it.
    """
    if value is None or value is UNDEFINED:
        return None
    if value <= 0:
        return 0
    return min(value, 1) * 100


PROXMOX_SENSOR_DISK: Final[tuple[ProxmoxSensorEntityDescription, ...]] = (
    ProxmoxSensorEntityDescription(
        key="disk_free",
        name="Disk free",
        icon="mdi:harddisk",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        value_fn=lambda x: (
            (x.disk_total - x.disk_used)
            if (UNDEFINED not in (x.disk_total, x.disk_used))
            else None
        ),
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        entity_registry_enabled_default=False,
        translation_key="disk_free",
    ),
    ProxmoxSensorEntityDescription(
        key="disk_free_perc",
        name="Disk free percentage",
        icon="mdi:harddisk",
        native_unit_of_measurement=PERCENTAGE,
        conversion_fn=percentage_or_unknown,
        value_fn=lambda x: (
            1 - (x.disk_used / x.disk_total)
            if (UNDEFINED not in (x.disk_used, x.disk_total) and x.disk_total > 0)
            else None
        ),
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
        translation_key="disk_free_perc",
    ),
    ProxmoxSensorEntityDescription(
        key=ProxmoxKeyAPIParse.DISK_TOTAL,
        name="Disk total",
        icon="mdi:harddisk",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        entity_registry_enabled_default=False,
        translation_key="disk_total",
    ),
    ProxmoxSensorEntityDescription(
        key=ProxmoxKeyAPIParse.DISK_USED,
        name="Disk used",
        icon="mdi:harddisk",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        entity_registry_enabled_default=False,
        translation_key="disk_used",
    ),
    ProxmoxSensorEntityDescription(
        key="disk_used_perc",
        name="Disk used percentage",
        icon="mdi:harddisk",
        native_unit_of_measurement=PERCENTAGE,
        conversion_fn=percentage_or_unknown,
        value_fn=lambda x: (
            (x.disk_used / x.disk_total)
            if (UNDEFINED not in (x.disk_used, x.disk_total) and x.disk_total > 0)
            else None
        ),
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        translation_key="disk_used_perc",
    ),
)
PROXMOX_SENSOR_MEMORY: Final[tuple[ProxmoxSensorEntityDescription, ...]] = (
    ProxmoxSensorEntityDescription(
        key=ProxmoxKeyAPIParse.MEMORY_FREE,
        name="Memory free",
        icon="mdi:memory",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        translation_key="memory_free",
    ),
    ProxmoxSensorEntityDescription(
        key="memory_free_perc",
        name="Memory free percentage",
        icon="mdi:memory",
        native_unit_of_measurement=PERCENTAGE,
        conversion_fn=percentage_or_unknown,
        value_fn=lambda x: (
            (x.memory_free / x.memory_total)
            if (UNDEFINED not in (x.memory_free, x.memory_total) and x.memory_total > 0)
            else None
        ),
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        translation_key="memory_free_perc",
    ),
    ProxmoxSensorEntityDescription(
        key=ProxmoxKeyAPIParse.MEMORY_TOTAL,
        name="Memory total",
        icon="mdi:memory",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        entity_registry_enabled_default=False,
        translation_key="memory_total",
    ),
    ProxmoxSensorEntityDescription(
        key=ProxmoxKeyAPIParse.MEMORY_USED,
        name="Memory used",
        icon="mdi:memory",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        translation_key="memory_used",
    ),
    ProxmoxSensorEntityDescription(
        key="memory_used_perc",
        name="Memory used percentage",
        icon="mdi:memory",
        native_unit_of_measurement=PERCENTAGE,
        conversion_fn=percentage_or_unknown,
        value_fn=lambda x: (
            (x.memory_used / x.memory_total)
            if (UNDEFINED not in (x.memory_used, x.memory_total) and x.memory_total > 0)
            else None
        ),
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        translation_key="memory_used_perc",
    ),
)
PROXMOX_SENSOR_SWAP: Final[tuple[ProxmoxSensorEntityDescription, ...]] = (
    ProxmoxSensorEntityDescription(
        key=ProxmoxKeyAPIParse.SWAP_FREE,
        name="Swap free",
        icon="mdi:memory",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        suggested_unit_of_measurement=UnitOfInformation.MEGABYTES,
        entity_registry_enabled_default=False,
        translation_key="swap_free",
    ),
    ProxmoxSensorEntityDescription(
        key="swap_free_perc",
        name="Swap free percentage",
        icon="mdi:memory",
        native_unit_of_measurement=PERCENTAGE,
        conversion_fn=lambda x: (x * 100) if x != UNDEFINED and x > 0 else 0,
        value_fn=lambda x: (
            (x.swap_free / x.swap_total)
            if (UNDEFINED not in (x.swap_free, x.swap_total) and x.swap_total > 0)
            else 0
        ),
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        translation_key="swap_free_perc",
    ),
    ProxmoxSensorEntityDescription(
        key=ProxmoxKeyAPIParse.SWAP_TOTAL,
        name="Swap total",
        icon="mdi:memory",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        suggested_unit_of_measurement=UnitOfInformation.MEGABYTES,
        entity_registry_enabled_default=False,
        translation_key="swap_total",
    ),
    ProxmoxSensorEntityDescription(
        key=ProxmoxKeyAPIParse.SWAP_USED,
        name="Swap used",
        icon="mdi:memory",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        suggested_unit_of_measurement=UnitOfInformation.MEGABYTES,
        entity_registry_enabled_default=False,
        translation_key="swap_used",
    ),
    ProxmoxSensorEntityDescription(
        key="swap_used_perc",
        name="Swap used percentage",
        icon="mdi:memory",
        native_unit_of_measurement=PERCENTAGE,
        conversion_fn=lambda x: (x * 100) if x != UNDEFINED and x > 0 else 0,
        value_fn=lambda x: (
            (x.swap_used / x.swap_total)
            if (UNDEFINED not in (x.swap_used, x.swap_total) and x.swap_total > 0)
            else 0
        ),
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        translation_key="swap_used_perc",
    ),
)
PROXMOX_SENSOR_UPTIME: Final[tuple[ProxmoxSensorEntityDescription, ...]] = (
    ProxmoxSensorEntityDescription(
        key=ProxmoxKeyAPIParse.UPTIME,
        name="Last boot",
        icon="mdi:database-clock-outline",
        conversion_fn=lambda x: (
            dt_util.utcnow() - timedelta(seconds=x) if x > 0 else None
        ),
        device_class=SensorDeviceClass.TIMESTAMP,
        # `utcnow() - uptime` lands a second or two off on every poll because
        # the API reports whole seconds, which would otherwise make every node
        # and guest record a new boot time once a minute. A real reboot moves
        # the value by far more than this margin and still comes through.
        stable_within=timedelta(minutes=1),
        translation_key="uptime",
    ),
)
PROXMOX_SENSOR_NETWORK: Final[tuple[ProxmoxSensorEntityDescription, ...]] = (
    ProxmoxSensorEntityDescription(
        key=ProxmoxKeyAPIParse.NETWORK_IN,
        name="Network in",
        icon="mdi:download-network-outline",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        suggested_unit_of_measurement=UnitOfInformation.MEGABYTES,
        entity_registry_enabled_default=False,
        translation_key="network_in",
    ),
    ProxmoxSensorEntityDescription(
        key=ProxmoxKeyAPIParse.NETWORK_OUT,
        name="Network out",
        icon="mdi:upload-network-outline",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        suggested_unit_of_measurement=UnitOfInformation.MEGABYTES,
        entity_registry_enabled_default=False,
        translation_key="network_out",
    ),
)
PROXMOX_SENSOR_CPU: Final[tuple[ProxmoxSensorEntityDescription, ...]] = (
    ProxmoxSensorEntityDescription(
        key=ProxmoxKeyAPIParse.CPU,
        name="CPU used",
        icon="mdi:cpu-64-bit",
        native_unit_of_measurement=PERCENTAGE,
        conversion_fn=lambda x: (x * 100) if x >= 0 else 0,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        translation_key="cpu_used",
    ),
)
PROXMOX_SENSOR_UPDATE: Final[tuple[ProxmoxSensorEntityDescription, ...]] = (
    ProxmoxSensorEntityDescription(
        key=ProxmoxKeyAPIParse.UPDATE_TOTAL,
        name="Total updates",
        icon="mdi:update",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        translation_key="updates_total",
        extra_attrs=[ProxmoxKeyAPIParse.UPDATE_LIST],
    ),
)
PROXMOX_SENSOR_NODES: Final[tuple[ProxmoxSensorEntityDescription, ...]] = (
    *PROXMOX_SENSOR_CPU,
    *PROXMOX_SENSOR_DISK,
    *PROXMOX_SENSOR_MEMORY,
    *PROXMOX_SENSOR_SWAP,
    *PROXMOX_SENSOR_UPTIME,
    ProxmoxSensorEntityDescription(
        key="qemu_on",
        name="Virtual machines running",
        icon="mdi:server",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        translation_key="qemu_on",
        extra_attrs=["qemu_on_list"],
    ),
    ProxmoxSensorEntityDescription(
        key="lxc_on",
        name="Containers running",
        icon="mdi:server",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        translation_key="lxc_on",
        extra_attrs=["lxc_on_list"],
    ),
)

PROXMOX_SENSOR_QEMU: Final[tuple[ProxmoxSensorEntityDescription, ...]] = (
    ProxmoxSensorEntityDescription(
        key="node",
        name="Node",
        icon="mdi:server",
        translation_key="node",
    ),
    ProxmoxSensorEntityDescription(
        key="status_raw",
        name="Status",
        icon="mdi:server",
        translation_key="status_raw",
        value_fn=lambda x: (
            x.health
            if (x.health not in ["running", "stopped", UNDEFINED])
            else x.status
        ),
    ),
    ProxmoxSensorEntityDescription(
        key=ProxmoxKeyAPIParse.GUEST_FILE_CONTENT,
        name="Guest file content",
        icon="mdi:file-document-outline",
        translation_key="guest_file_content",
        # HA truncates entity state to 255 chars; the full (still capped)
        # content read from the guest is available as an attribute.
        conversion_fn=lambda x: x[:255] if isinstance(x, str) else x,
        extra_attrs=[
            ProxmoxKeyAPIParse.GUEST_FILE_PATH,
            ProxmoxKeyAPIParse.GUEST_FILE_CONTENT,
        ],
    ),
    *PROXMOX_SENSOR_CPU,
    *PROXMOX_SENSOR_DISK,
    *PROXMOX_SENSOR_MEMORY,
    *PROXMOX_SENSOR_NETWORK,
    *PROXMOX_SENSOR_UPTIME,
)

PROXMOX_SENSOR_LXC: Final[tuple[ProxmoxSensorEntityDescription, ...]] = (
    ProxmoxSensorEntityDescription(
        key="node",
        name="Node",
        icon="mdi:server",
    ),
    *PROXMOX_SENSOR_CPU,
    *PROXMOX_SENSOR_DISK,
    *PROXMOX_SENSOR_MEMORY,
    *PROXMOX_SENSOR_NETWORK,
    *PROXMOX_SENSOR_SWAP,
    *PROXMOX_SENSOR_UPTIME,
)

PROXMOX_SENSOR_STORAGE: Final[tuple[ProxmoxSensorEntityDescription, ...]] = (
    ProxmoxSensorEntityDescription(
        key="node",
        name="Node",
        icon="mdi:server",
        translation_key="node",
    ),
    *PROXMOX_SENSOR_DISK,
)


PROXMOX_SENSOR_DISKS: Final[tuple[ProxmoxSensorEntityDescription, ...]] = (
    ProxmoxSensorEntityDescription(
        key="node",
        name="Node",
        icon="mdi:server",
        translation_key="node",
    ),
    ProxmoxSensorEntityDescription(
        key="size",
        name="Size",
        icon="mdi:harddisk",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        translation_key="disk_size",
    ),
    ProxmoxSensorEntityDescription(
        key="disk_rpm",
        name="Disk speed",
        icon="mdi:speedometer",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=REVOLUTIONS_PER_MINUTE,
        suggested_display_precision=0,
        translation_key="disk_rpm",
        entity_registry_enabled_default=False,
    ),
    ProxmoxSensorEntityDescription(
        key="temperature",
        name="Temperature",
        icon="mdi:harddisk",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        translation_key="temperature",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    ProxmoxSensorEntityDescription(
        key="temperature_air",
        name="Airflow temperature",
        icon="mdi:harddisk",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        translation_key="temperature_air",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    ProxmoxSensorEntityDescription(
        key="power_cycles",
        name="Power cycles",
        icon="mdi:reload",
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
        translation_key="power_cycles",
    ),
    ProxmoxSensorEntityDescription(
        key="power_loss",
        name="Unexpected power loss",
        icon="mdi:flash-alert-outline",
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
        translation_key="power_loss",
    ),
    ProxmoxSensorEntityDescription(
        key="power_hours",
        name="Power-on Hours",
        icon="mdi:power-settings",
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=0,
        translation_key="power_hours",
    ),
    ProxmoxSensorEntityDescription(
        key="life_left",
        name="Life left",
        icon="mdi:harddisk-remove",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        translation_key="life_left",
    ),
    ProxmoxSensorEntityDescription(
        key="disk_wearout",
        name="Wearout",
        icon="mdi:clipboard-pulse-outline",
        native_unit_of_measurement=PERCENTAGE,
        conversion_fn=lambda x: (100 - x) if x != UNDEFINED else None,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        translation_key="disk_wearout",
    ),
)

PROXMOX_SENSOR_ZFS: Final[tuple[ProxmoxSensorEntityDescription, ...]] = (
    ProxmoxSensorEntityDescription(
        key="health",
        name="Health",
        icon="mdi:nas",
        translation_key="zfs_health",
    ),
    ProxmoxSensorEntityDescription(
        key="free_perc",
        name="Free percentage",
        icon="mdi:nas",
        native_unit_of_measurement=PERCENTAGE,
        conversion_fn=lambda x: (x * 100) if x != UNDEFINED and x > 0 else 0,
        value_fn=lambda x: (
            (x.free / x.size)
            if (UNDEFINED not in (x.free, x.size) and x.size > 0)
            else 0
        ),
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        translation_key="zfs_free_perc",
    ),
    ProxmoxSensorEntityDescription(
        key="size",
        name="Size",
        icon="mdi:nas",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        translation_key="zfs_total",
    ),
    ProxmoxSensorEntityDescription(
        key="alloc",
        name="Used",
        icon="mdi:nas",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        translation_key="zfs_used",
    ),
    ProxmoxSensorEntityDescription(
        key="used_perc",
        name="Used percentage",
        icon="mdi:nas",
        native_unit_of_measurement=PERCENTAGE,
        conversion_fn=lambda x: (x * 100) if x != UNDEFINED and x > 0 else 0,
        value_fn=lambda x: (
            (x.alloc / x.size)
            if (UNDEFINED not in (x.alloc, x.size) and x.size > 0)
            else 0
        ),
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        translation_key="zfs_used_perc",
    ),
)

PROXMOX_SENSOR_TASKS: Final[tuple[ProxmoxSensorEntityDescription, ...]] = (
    ProxmoxSensorEntityDescription(
        key="failed_tasks_count",
        name="Failed tasks",
        icon="mdi:alert-circle",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        extra_attrs=["recent_failures", "last_failure_time"],
        translation_key="failed_tasks_count",
        value_fn=lambda x: x.failed_count,
    ),
)


PROXMOX_SENSOR_BACKUP_INFO: Final[tuple[ProxmoxSensorEntityDescription, ...]] = (
    ProxmoxSensorEntityDescription(
        key="guests_without_backup",
        name="Guests without backup",
        icon="mdi:backup-restore",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        extra_attrs=["guests"],
        translation_key="guests_without_backup",
    ),
)


PROXMOX_SENSOR_CEPH: Final[tuple[ProxmoxSensorEntityDescription, ...]] = (
    ProxmoxSensorEntityDescription(
        key="health",
        name="Ceph health",
        icon="mdi:database-check-outline",
        device_class=SensorDeviceClass.ENUM,
        options=["ok", "warning", "error"],
        entity_registry_enabled_default=False,
        extra_attrs=["checks"],
        translation_key="ceph_health",
    ),
)


PROXMOX_SENSOR_REPLICATION: Final[tuple[ProxmoxSensorEntityDescription, ...]] = (
    ProxmoxSensorEntityDescription(
        key="oldest_sync",
        name="Replication last sync",
        icon="mdi:folder-sync-outline",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        translation_key="replication_last_sync",
    ),
)


PROXMOX_SENSOR_SUBSCRIPTION: Final[tuple[ProxmoxSensorEntityDescription, ...]] = (
    ProxmoxSensorEntityDescription(
        key="status",
        name="Subscription",
        icon="mdi:license",
        device_class=SensorDeviceClass.ENUM,
        options=["new", "notfound", "active", "invalid", "expired", "suspended"],
        entity_category=EntityCategory.DIAGNOSTIC,
        # Most installations run without a subscription, where this reads
        # "notfound" forever; it is worth having only once there is one.
        entity_registry_enabled_default=False,
        extra_attrs=["level", "product", "next_due"],
        translation_key="subscription_status",
    ),
)


PROXMOX_SENSOR_CERTIFICATE: Final[tuple[ProxmoxSensorEntityDescription, ...]] = (
    ProxmoxSensorEntityDescription(
        key="expires",
        name="Certificate expires",
        icon="mdi:certificate",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        # Most installations serve the cluster CA's own certificate, where an
        # expiry years away is not worth an entity unless asked for.
        entity_registry_enabled_default=False,
        extra_attrs=["filename", "subject", "issuer"],
        translation_key="certificate_expires",
    ),
)


PROXMOX_SENSOR_HA_STATUS: Final[tuple[ProxmoxSensorEntityDescription, ...]] = (
    ProxmoxSensorEntityDescription(
        key="armed_state",
        name="HA armed state",
        icon="mdi:shield-half-full",
        device_class=SensorDeviceClass.ENUM,
        options=["armed", "standby", "disarming", "disarmed"],
        extra_attrs=["resource_mode"],
        translation_key="ha_armed_state",
    ),
    ProxmoxSensorEntityDescription(
        key="crm_master",
        name="CRM master",
        icon="mdi:crown-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="ha_crm_master",
    ),
    ProxmoxSensorEntityDescription(
        key="crm_master_last_seen",
        name="CRM master last seen",
        icon="mdi:clock-check-outline",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        # The CRM rewrites this timestamp every few seconds, so the value
        # differs on every poll and each poll would be recorded as a state
        # change. The `CRM master stale` binary sensor covers the part that
        # matters; this stays available for debugging, but off by default.
        entity_registry_enabled_default=False,
        translation_key="ha_crm_master_last_seen",
    ),
    ProxmoxSensorEntityDescription(
        key="ha_resources_total",
        name="HA resources",
        icon="mdi:server",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        translation_key="ha_resources_total",
    ),
    ProxmoxSensorEntityDescription(
        key="ha_resources_error",
        name="HA resources in error",
        icon="mdi:alert-circle-outline",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        extra_attrs=["ha_resources_error_list"],
        translation_key="ha_resources_error",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor."""
    async_add_entities(await async_setup_sensors_nodes(hass, config_entry))
    async_add_entities(await async_setup_sensors_qemu(hass, config_entry))
    async_add_entities(await async_setup_sensors_lxc(hass, config_entry))
    async_add_entities(await async_setup_sensors_storages(hass, config_entry))
    async_add_entities(await async_setup_sensors_tasks(hass, config_entry))
    async_add_entities(await async_setup_hardware_sensors(hass, config_entry))
    async_add_entities(await async_setup_sensors_ha_status(hass, config_entry))
    async_add_entities(await async_setup_sensors_certificates(hass, config_entry))
    async_add_entities(await async_setup_sensors_backup_info(hass, config_entry))
    async_add_entities(await async_setup_sensors_subscription(hass, config_entry))
    async_add_entities(await async_setup_sensors_replication(hass, config_entry))
    async_add_entities(await async_setup_sensors_ceph(hass, config_entry))


async def async_setup_sensors_ha_status(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> list:
    """Set up the cluster HA status sensors."""
    coordinators = config_entry.runtime_data[COORDINATORS]

    # Only present when the optional cluster HA administration credentials
    # are configured and could be authenticated.
    if (
        coordinator := coordinators.get(f"{ProxmoxType.Proxmox}_ha_status")
    ) is None or coordinator.data is None:
        return []

    return [
        create_sensor(
            coordinator=coordinator,
            info_device=device_info(
                hass=hass,
                config_entry=config_entry,
                api_category=ProxmoxType.Proxmox,
            ),
            description=description,
            resource_id="cluster",
            config_entry=config_entry,
        )
        for description in PROXMOX_SENSOR_HA_STATUS
        # A field the cluster does not report at all (no fencing entry
        # before pve-ha-manager 5.1.3, no CRM master before HA is
        # configured) gets no entity rather than a permanently unknown one.
        if getattr(coordinator.data, description.key, UNDEFINED) is not UNDEFINED
    ]


async def async_setup_sensors_backup_info(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> list:
    """Set up the backup coverage sensor."""
    coordinators = config_entry.runtime_data[COORDINATORS]

    # Only present when the optional cluster credentials are configured and
    # could be authenticated; the endpoint needs Sys.Audit on `/`.
    if (
        coordinator := coordinators.get(f"{ProxmoxType.Proxmox}_backup_info")
    ) is None or coordinator.data is None:
        return []

    return [
        create_sensor(
            coordinator=coordinator,
            info_device=device_info(
                hass=hass,
                config_entry=config_entry,
                api_category=ProxmoxType.Proxmox,
            ),
            description=description,
            resource_id="cluster",
            config_entry=config_entry,
        )
        for description in PROXMOX_SENSOR_BACKUP_INFO
    ]


async def async_setup_sensors_ceph(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> list:
    """Set up the Ceph health sensor."""
    coordinators = config_entry.runtime_data[COORDINATORS]

    # Only present on a cluster that actually runs Ceph, and only when the
    # optional cluster credentials are configured.
    if (
        coordinator := coordinators.get(f"{ProxmoxType.Proxmox}_ceph")
    ) is None or coordinator.data is None:
        return []

    return [
        create_sensor(
            coordinator=coordinator,
            info_device=device_info(
                hass=hass,
                config_entry=config_entry,
                api_category=ProxmoxType.Proxmox,
            ),
            description=description,
            resource_id="cluster",
            config_entry=config_entry,
        )
        for description in PROXMOX_SENSOR_CEPH
        if getattr(coordinator.data, description.key, UNDEFINED) is not UNDEFINED
    ]


async def async_setup_sensors_replication(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> list:
    """Set up the per-node replication sensors."""
    coordinators = config_entry.runtime_data[COORDINATORS]
    sensors = []

    for node in config_entry.data[CONF_NODES]:
        coordinator = coordinators.get(f"{ProxmoxType.Replication}_{node}")
        # A node with no replication jobs gets no entity at all, rather than
        # one that can only ever say "nothing to report".
        if coordinator is None or coordinator.data is None or not coordinator.data.jobs:
            continue

        sensors.extend(
            create_sensor(
                coordinator=coordinator,
                info_device=device_info(
                    hass=hass,
                    config_entry=config_entry,
                    api_category=ProxmoxType.Node,
                    node=node,
                ),
                description=description,
                resource_id=f"{ProxmoxType.Replication}_{node}",
                config_entry=config_entry,
            )
            for description in PROXMOX_SENSOR_REPLICATION
            if getattr(coordinator.data, description.key, UNDEFINED) is not UNDEFINED
        )

    return sensors


async def async_setup_sensors_subscription(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> list:
    """Set up the per-node subscription sensors."""
    coordinators = config_entry.runtime_data[COORDINATORS]
    sensors = []

    for node in config_entry.data[CONF_NODES]:
        coordinator = coordinators.get(f"{ProxmoxType.Subscription}_{node}")
        if coordinator is None or coordinator.data is None:
            continue

        sensors.extend(
            create_sensor(
                coordinator=coordinator,
                info_device=device_info(
                    hass=hass,
                    config_entry=config_entry,
                    api_category=ProxmoxType.Node,
                    node=node,
                ),
                description=description,
                resource_id=f"{ProxmoxType.Subscription}_{node}",
                config_entry=config_entry,
            )
            for description in PROXMOX_SENSOR_SUBSCRIPTION
            if getattr(coordinator.data, description.key, UNDEFINED) is not UNDEFINED
        )

    return sensors


async def async_setup_sensors_certificates(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> list:
    """Set up the per-node certificate sensors."""
    coordinators = config_entry.runtime_data[COORDINATORS]
    sensors = []

    for node in config_entry.data[CONF_NODES]:
        coordinator = coordinators.get(f"{ProxmoxType.Certificate}_{node}")
        if coordinator is None or coordinator.data is None:
            continue

        sensors.extend(
            create_sensor(
                coordinator=coordinator,
                info_device=device_info(
                    hass=hass,
                    config_entry=config_entry,
                    api_category=ProxmoxType.Node,
                    node=node,
                ),
                description=description,
                resource_id=f"{ProxmoxType.Certificate}_{node}",
                config_entry=config_entry,
            )
            for description in PROXMOX_SENSOR_CERTIFICATE
            # A node that reports no usable certificate gets no entity rather
            # than one that is permanently unknown.
            if getattr(coordinator.data, description.key, UNDEFINED) is not UNDEFINED
        )

    return sensors


async def async_setup_sensors_nodes(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> list:
    """Set up sensor."""
    sensors = []
    migrate_unique_id_disks = []

    coordinators = coordinator = config_entry.runtime_data[COORDINATORS]

    for node in config_entry.data[CONF_NODES]:
        if f"{ProxmoxType.Node}_{node}" in coordinators:
            coordinator = coordinators[f"{ProxmoxType.Node}_{node}"]
        else:
            continue

        if coordinator.data is not None:
            for description in PROXMOX_SENSOR_NODES:
                if (
                    (data_value := getattr(coordinator.data, description.key, False))
                    # and data_value != UNDEFINED
                    or data_value == 0
                    or (
                        (value := description.value_fn) is not None
                        and value(coordinator.data) is not None
                    )
                ):
                    sensors.append(
                        create_sensor(
                            coordinator=coordinator,
                            info_device=device_info(
                                hass=hass,
                                config_entry=config_entry,
                                api_category=ProxmoxType.Node,
                                node=node,
                            ),
                            description=description,
                            resource_id=node,
                            config_entry=config_entry,
                        )
                    )

            if f"{ProxmoxType.Update}_{node}" in coordinators:
                coordinator_updates = coordinators[f"{ProxmoxType.Update}_{node}"]
                for description in PROXMOX_SENSOR_UPDATE:
                    if (
                        (
                            (
                                data_value := getattr(
                                    coordinator_updates.data, description.key, False
                                )
                            )
                            and data_value != UNDEFINED
                        )
                        or data_value == 0
                        or (
                            (value := description.value_fn) is not None
                            and value(coordinator_updates.data) is not None
                        )
                    ):
                        sensors.append(
                            create_sensor(
                                coordinator=coordinator_updates,
                                info_device=device_info(
                                    hass=hass,
                                    config_entry=config_entry,
                                    api_category=ProxmoxType.Update,
                                    node=node,
                                ),
                                description=description,
                                resource_id=node,
                                config_entry=config_entry,
                            )
                        )

            coordinator_disks_data: ProxmoxDiskData
            for coordinator_disk in coordinators.get(f"{ProxmoxType.Disk}_{node}", []):
                if (coordinator_disks_data := coordinator_disk.data) is None:
                    continue

                for description in PROXMOX_SENSOR_DISKS:
                    if (
                        (
                            (
                                data_value := getattr(
                                    coordinator_disk.data, description.key, False
                                )
                            )
                            and data_value != UNDEFINED
                        )
                        or data_value == 0
                        or (
                            (value := description.value_fn) is not None
                            and value(coordinator_disk.data) is not None
                        )
                    ):
                        migrate_unique_id_disks.append(
                            {
                                "old_unique_id": f"{config_entry.entry_id}_{coordinator_disks_data.path}_{description.key}",
                                "new_unique_id": f"{config_entry.entry_id}_{node}_{coordinator_disks_data.disk_id}_{description.key}",
                            }
                        )
                        migrate_unique_id_disks.append(
                            {
                                "old_unique_id": f"{config_entry.entry_id}_{node}_{coordinator_disks_data.path}_{description.key}",
                                "new_unique_id": f"{config_entry.entry_id}_{node}_{coordinator_disks_data.disk_id}_{description.key}",
                            }
                        )
                        if (
                            coordinator_disks_data.wwn
                            and coordinator_disks_data.wwn
                            != coordinator_disks_data.disk_id
                        ):
                            migrate_unique_id_disks.append(
                                {
                                    "old_unique_id": f"{config_entry.entry_id}_{node}_{coordinator_disks_data.wwn}_{description.key}",
                                    "new_unique_id": f"{config_entry.entry_id}_{node}_{coordinator_disks_data.disk_id}_{description.key}",
                                }
                            )
                        await async_migrate_old_unique_ids(
                            hass, Platform.SENSOR, migrate_unique_id_disks
                        )
                        sensors.append(
                            create_sensor(
                                coordinator=coordinator_disk,
                                info_device=device_info(
                                    hass=hass,
                                    config_entry=config_entry,
                                    api_category=ProxmoxType.Disk,
                                    node=node,
                                    resource_id=coordinator_disks_data.disk_id,
                                    cordinator_resource=coordinator_disks_data,
                                ),
                                description=description,
                                resource_id=f"{node}_{coordinator_disks_data.disk_id}",
                                config_entry=config_entry,
                            )
                        )

            coordinator_zfs_data: ProxmoxZFSData
            for coordinator_zfs in coordinators.get(f"{ProxmoxType.ZFS}_{node}", []):
                if (coordinator_zfs_data := coordinator_zfs.data) is None:
                    continue

                for description in PROXMOX_SENSOR_ZFS:
                    if (
                        (
                            (
                                data_value := getattr(
                                    coordinator_zfs.data, description.key, False
                                )
                            )
                            and data_value != UNDEFINED
                        )
                        or data_value == 0
                        or (
                            (value := description.value_fn) is not None
                            and value(coordinator_zfs.data) is not None
                        )
                    ):
                        sensors.append(
                            create_sensor(
                                coordinator=coordinator_zfs,
                                info_device=device_info(
                                    hass=hass,
                                    config_entry=config_entry,
                                    api_category=ProxmoxType.ZFS,
                                    node=node,
                                    resource_id=coordinator_zfs_data.name,
                                    cordinator_resource=coordinator_zfs_data,
                                ),
                                description=description,
                                resource_id=f"{node}_{coordinator_zfs_data.name}",
                                config_entry=config_entry,
                            )
                        )

    return sensors


async def async_setup_sensors_qemu(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> list:
    """Set up sensor."""
    sensors = []

    coordinators = config_entry.runtime_data[COORDINATORS]

    for vm_id in config_entry.data[CONF_QEMU]:
        if f"{ProxmoxType.QEMU}_{vm_id}" in coordinators:
            coordinator = coordinators[f"{ProxmoxType.QEMU}_{vm_id}"]
        else:
            continue

        if coordinator.data is None:
            continue

        for description in PROXMOX_SENSOR_QEMU:
            if description.api_category in (None, ProxmoxType.QEMU) and (
                (
                    (data_value := getattr(coordinator.data, description.key, False))
                    and data_value != UNDEFINED
                )
                or data_value == 0
                or (
                    (value := description.value_fn) is not None
                    and value(coordinator.data) is not None
                )
            ):
                sensors.append(
                    create_sensor(
                        coordinator=coordinator,
                        info_device=device_info(
                            hass=hass,
                            config_entry=config_entry,
                            api_category=ProxmoxType.QEMU,
                            resource_id=vm_id,
                        ),
                        description=description,
                        resource_id=vm_id,
                        config_entry=config_entry,
                    )
                )

    return sensors


async def async_setup_sensors_lxc(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> list:
    """Set up sensor."""
    sensors = []

    coordinators = config_entry.runtime_data[COORDINATORS]

    for ct_id in config_entry.data[CONF_LXC]:
        if f"{ProxmoxType.LXC}_{ct_id}" in coordinators:
            coordinator = coordinators[f"{ProxmoxType.LXC}_{ct_id}"]
        else:
            continue

        if coordinator.data is None:
            continue

        for description in PROXMOX_SENSOR_LXC:
            if description.api_category in (None, ProxmoxType.LXC) and (
                (
                    (data_value := getattr(coordinator.data, description.key, False))
                    and data_value != UNDEFINED
                )
                or data_value == 0
                or (
                    (value := description.value_fn) is not None
                    and value(coordinator.data) is not None
                )
            ):
                sensors.append(
                    create_sensor(
                        coordinator=coordinator,
                        info_device=device_info(
                            hass=hass,
                            config_entry=config_entry,
                            api_category=ProxmoxType.LXC,
                            resource_id=ct_id,
                        ),
                        description=description,
                        resource_id=ct_id,
                        config_entry=config_entry,
                    )
                )

    return sensors


async def async_setup_sensors_storages(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> list:
    """Set up sensor."""
    sensors = []

    coordinators = config_entry.runtime_data[COORDINATORS]

    for storage_id in config_entry.data[CONF_STORAGE]:
        if f"{ProxmoxType.Storage}_{storage_id}" in coordinators:
            coordinator = coordinators[f"{ProxmoxType.Storage}_{storage_id}"]
        else:
            continue

        if coordinator.data is None:
            continue

        for description in PROXMOX_SENSOR_STORAGE:
            if description.api_category in (None, ProxmoxType.Storage) and (
                (
                    (data_value := getattr(coordinator.data, description.key, False))
                    and data_value != UNDEFINED
                )
                or data_value == 0
                or (
                    (value := description.value_fn) is not None
                    and value(coordinator.data) is not None
                )
            ):
                sensors.append(
                    create_sensor(
                        coordinator=coordinator,
                        info_device=device_info(
                            hass=hass,
                            config_entry=config_entry,
                            api_category=ProxmoxType.Storage,
                            resource_id=storage_id,
                            cordinator_resource=coordinator.data,
                        ),
                        description=description,
                        resource_id=storage_id,
                        config_entry=config_entry,
                    )
                )

    return sensors


def create_sensor(
    coordinator: DataUpdateCoordinator,
    info_device: DeviceInfo,
    description: ProxmoxSensorEntityDescription,
    config_entry: ConfigEntry,
    resource_id: str | None = None,
) -> ProxmoxSensorEntity:
    """Create a sensor based on the given data."""
    return ProxmoxSensorEntity(
        coordinator=coordinator,
        description=description,
        unique_id=f"{config_entry.entry_id}_{resource_id}_{description.key}",
        info_device=info_device,
    )


class ProxmoxSensorEntity(ProxmoxEntity, SensorEntity):
    """A sensor for reading Proxmox VE data."""

    entity_description: ProxmoxSensorEntityDescription

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        info_device: DeviceInfo,
        description: ProxmoxSensorEntityDescription,
        unique_id: str,
    ) -> None:
        """Create the button for vms or containers."""
        super().__init__(coordinator, unique_id, description)

        self._attr_device_info = info_device
        self.entity_description = description
        self._stable_value: datetime | None = None

    @property
    def native_value(self) -> StateType:
        """Return the units of the sensor."""
        if (data := self.coordinator.data) is None:
            return None

        if (not getattr(data, self.entity_description.key, False)) and getattr(
            data, self.entity_description.key, True
        ) != 0:
            if value := self.entity_description.value_fn:
                native_value = value(data)
            elif self.entity_description.key in (
                ProxmoxKeyAPIParse.CPU,
                ProxmoxKeyAPIParse.UPDATE_TOTAL,
                ProxmoxKeyAPIParse.MEMORY_USED,
                ProxmoxKeyAPIParse.DISK_USED,
                ProxmoxKeyAPIParse.SWAP_USED,
                "lxc_on",
                "qemu_on",
            ):
                return 0
            else:
                return None
        elif getattr(data, self.entity_description.key, False) == UNDEFINED:
            return None
        else:
            native_value = getattr(data, self.entity_description.key)

        if (conversion := self.entity_description.conversion_fn) is not None:
            native_value = conversion(native_value)

        return self._hold_steady(native_value)

    def _hold_steady(self, native_value: Any) -> Any:
        """
        Suppress noise around an unchanged timestamp.

        A boot time computed as `now - uptime` moves by a second or two on
        every poll even while the machine keeps running, and each of those
        writes a state change. Keep reporting the value already published
        until the new one leaves the description's margin.
        """
        if (margin := self.entity_description.stable_within) is None:
            return native_value

        if not isinstance(native_value, datetime):
            return native_value

        if (
            self._stable_value is not None
            and abs(native_value - self._stable_value) <= margin
        ):
            return self._stable_value

        self._stable_value = native_value
        return native_value

    @property
    def available(self) -> bool:
        """Return sensor availability."""
        return super().available and self.coordinator.data is not None

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return the extra attributes of the sensor."""
        if self.entity_description.extra_attrs is None:
            return None

        if (data := self.coordinator.data) is None:
            return None

        return {
            attr: getattr(data, attr, False)
            for attr in self.entity_description.extra_attrs
        }


async def async_setup_sensors_tasks(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> list:
    """Set up task sensors."""
    sensors = []
    coordinators = config_entry.runtime_data[COORDINATORS]

    for node in config_entry.data[CONF_NODES]:
        coordinator_key = f"{ProxmoxType.Tasks}_{node}"
        if coordinator_key in coordinators:
            coordinator = coordinators[coordinator_key]
            for description in PROXMOX_SENSOR_TASKS:
                unique_id = (
                    f"{config_entry.entry_id}_{coordinator_key}_{description.key}"
                )
                sensors.append(
                    ProxmoxSensorEntity(
                        coordinator=coordinator,
                        info_device=device_info(
                            hass=hass,
                            config_entry=config_entry,
                            api_category=ProxmoxType.Node,
                            node=node,
                        ),
                        description=description,
                        unique_id=unique_id,
                    )
                )

    return sensors


async def async_setup_hardware_sensors(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> list:
    """Set up hardware sensor entities from sensors -j output."""
    sensors = []
    coordinators = config_entry.runtime_data[COORDINATORS]

    for node in config_entry.data[CONF_NODES]:
        coordinator_key = f"{ProxmoxType.Node}_{node}"
        if coordinator_key not in coordinators:
            continue
        coordinator = coordinators[coordinator_key]
        if coordinator.data is None or not coordinator.data.sensors:
            continue

        for sensor_key in coordinator.data.sensors:
            if coordinator.data.sensors[sensor_key] is None:
                continue
            info = _classify_sensor_key(sensor_key)

            description = ProxmoxSensorEntityDescription(
                key="hw_sensor",
                name=info["name"],
                icon=info["icon"],
                native_unit_of_measurement=info["native_unit"],
                device_class=info["device_class"],
                state_class=SensorStateClass.MEASUREMENT,
                suggested_display_precision=info["suggested_precision"],
                conversion_fn=info["conversion_fn"],
                entity_registry_enabled_default=True,
                entity_category=EntityCategory.DIAGNOSTIC,
                value_fn=lambda data, key=sensor_key: data.sensors.get(key),
            )
            sensors.append(
                create_sensor(
                    coordinator=coordinator,
                    info_device=device_info(
                        hass=hass,
                        config_entry=config_entry,
                        api_category=ProxmoxType.Node,
                        node=node,
                    ),
                    description=description,
                    resource_id=f"{node}_{sensor_key}_sensor",
                    config_entry=config_entry,
                )
            )

    return sensors
