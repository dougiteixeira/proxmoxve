"""Sensor to read Proxmox VE data."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Final

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    REVOLUTIONS_PER_MINUTE,
    Platform,
    UnitOfInformation,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import UNDEFINED, StateType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
import homeassistant.util.dt as dt_util

from . import async_migrate_old_unique_ids, device_info
from .const import (
    CONF_LXC,
    CONF_NODES,
    CONF_QEMU,
    CONF_STORAGE,
    COORDINATORS,
    DOMAIN,
    ProxmoxKeyAPIParse,
    ProxmoxType,
)
from .entity import ProxmoxEntity, ProxmoxEntityDescription


@dataclass(frozen=True, kw_only=True)
class ProxmoxSensorEntityDescription(ProxmoxEntityDescription, SensorEntityDescription):
    """Class describing Proxmox sensor entities."""

    conversion_fn: Callable | None = None  # conversion factor to be applied to units
    value_fn: Callable[[Any], Any | str] | None = None
    api_category: ProxmoxType | None = (
        None  # Set when the sensor applies to only QEMU or LXC, if None applies to both.
    )
    extra_attrs: list[str] | None = None


PROXMOX_SENSOR_DISK: Final[tuple[ProxmoxSensorEntityDescription, ...]] = (
    ProxmoxSensorEntityDescription(
        key="disk_free",
        name="Disk free",
        icon="mdi:harddisk",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        value_fn=lambda x: (x.disk_total - x.disk_used),
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
        conversion_fn=lambda x: (x * 100) if x > 0 else 0,
        value_fn=lambda x: 1 - (x.disk_used / x.disk_total) if x.disk_total > 0 else 0,
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
        conversion_fn=lambda x: (x * 100) if x > 0 else 0,
        value_fn=lambda x: (x.disk_used / x.disk_total) if x.disk_total > 0 else 0,
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
        conversion_fn=lambda x: (x * 100) if x > 0 else 0,
        value_fn=lambda x: (x.memory_free / x.memory_total)
        if x.memory_total > 0
        else 0,
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
        conversion_fn=lambda x: (x * 100) if x > 0 else 0,
        value_fn=lambda x: (x.memory_used / x.memory_total)
        if x.memory_total > 0
        else 0,
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
        conversion_fn=lambda x: (x * 100) if x > 0 else 0,
        value_fn=lambda x: (x.swap_free / x.swap_total) if x.swap_total > 0 else 0,
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
        conversion_fn=lambda x: (x * 100) if x > 0 else 0,
        value_fn=lambda x: (x.swap_used / x.swap_total) if x.swap_total > 0 else 0,
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
        value_fn=lambda x: x.health
        if x.health not in ["running", "stopped"]
        else x.status,
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
        conversion_fn=lambda x: (100 - x) / 100 if x != UNDEFINED else None,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        translation_key="disk_wearout",
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


async def async_setup_sensors_nodes(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> list:
    """Set up sensor."""

    sensors = []
    migrate_unique_id_disks = []

    coordinators = hass.data[DOMAIN][config_entry.entry_id][COORDINATORS]

    for node in config_entry.data[CONF_NODES]:
        if f"{ProxmoxType.Node}_{node}" in coordinators:
            coordinator = coordinators[f"{ProxmoxType.Node}_{node}"]
        else:
            continue

        if coordinator.data is not None:
            for description in PROXMOX_SENSOR_NODES:
                if (
                    (
                        (
                            data_value := getattr(
                                coordinator.data, description.key, False
                            )
                        )
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
            for coordinator_disk in (
                coordinators[f"{ProxmoxType.Disk}_{node}"]
                if f"{ProxmoxType.Disk}_{node}" in coordinators
                else []
            ):
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
                        sensors.append(
                            create_sensor(
                                coordinator=coordinator_disk,
                                info_device=device_info(
                                    hass=hass,
                                    config_entry=config_entry,
                                    api_category=ProxmoxType.Disk,
                                    node=node,
                                    resource_id=coordinator_disks_data.path,
                                    cordinator_resource=coordinator_disks_data,
                                ),
                                description=description,
                                resource_id=f"{node}_{coordinator_disks_data.path}",
                                config_entry=config_entry,
                            )
                        )
                        migrate_unique_id_disks.append(
                            {
                                "old_unique_id": f"{config_entry.entry_id}_{coordinator_disks_data.path}_{description.key}",
                                "new_unique_id": f"{config_entry.entry_id}_{node}_{coordinator_disks_data.path}_{description.key}",
                            }
                        )

    await async_migrate_old_unique_ids(hass, Platform.SENSOR, migrate_unique_id_disks)
    return sensors


async def async_setup_sensors_qemu(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> list:
    """Set up sensor."""

    sensors = []

    coordinators = hass.data[DOMAIN][config_entry.entry_id][COORDINATORS]

    for vm_id in config_entry.data[CONF_QEMU]:
        if f"{ProxmoxType.QEMU}_{vm_id}" in coordinators:
            coordinator = coordinators[f"{ProxmoxType.QEMU}_{vm_id}"]
        else:
            continue

        if coordinator.data is None:
            continue

        for description in PROXMOX_SENSOR_QEMU:
            if description.api_category in (None, ProxmoxType.QEMU):
                if (
                    (
                        (
                            data_value := getattr(
                                coordinator.data, description.key, False
                            )
                        )
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

    coordinators = hass.data[DOMAIN][config_entry.entry_id][COORDINATORS]

    for ct_id in config_entry.data[CONF_LXC]:
        if f"{ProxmoxType.LXC}_{ct_id}" in coordinators:
            coordinator = coordinators[f"{ProxmoxType.LXC}_{ct_id}"]
        else:
            continue

        if coordinator.data is None:
            continue

        for description in PROXMOX_SENSOR_LXC:
            if description.api_category in (None, ProxmoxType.LXC):
                if (
                    (
                        (
                            data_value := getattr(
                                coordinator.data, description.key, False
                            )
                        )
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

    coordinators = hass.data[DOMAIN][config_entry.entry_id][COORDINATORS]

    for storage_id in config_entry.data[CONF_STORAGE]:
        if f"{ProxmoxType.Storage}_{storage_id}" in coordinators:
            coordinator = coordinators[f"{ProxmoxType.Storage}_{storage_id}"]
        else:
            continue

        if coordinator.data is None:
            continue

        for description in PROXMOX_SENSOR_STORAGE:
            if description.api_category in (None, ProxmoxType.Storage):
                if (
                    (
                        (
                            data_value := getattr(
                                coordinator.data, description.key, False
                            )
                        )
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

    @property
    def native_value(self) -> StateType:
        """Return the units of the sensor."""
        if (data := self.coordinator.data) is None:
            return None

        if not getattr(data, self.entity_description.key, False):
            if value := self.entity_description.value_fn:
                native_value = value(data)
            elif self.entity_description.key in (
                ProxmoxKeyAPIParse.CPU,
                ProxmoxKeyAPIParse.UPDATE_TOTAL,
                ProxmoxKeyAPIParse.MEMORY_USED,
                ProxmoxKeyAPIParse.DISK_USED,
                ProxmoxKeyAPIParse.SWAP_USED,
            ):
                return 0
            else:
                return None
        elif getattr(data, self.entity_description.key, False) == UNDEFINED:
            return None
        else:
            native_value = getattr(data, self.entity_description.key)

        if (conversion := self.entity_description.conversion_fn) is not None:
            return conversion(native_value)

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
