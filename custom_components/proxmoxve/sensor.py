"""Sensor to read Proxmox VE data."""
from __future__ import annotations

from collections.abc import Callable
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
from homeassistant.const import PERCENTAGE, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
import homeassistant.util.dt as dt_util

from . import device_info
from .const import (
    CONF_LXC,
    CONF_NODES,
    CONF_QEMU,
    COORDINATORS,
    DOMAIN,
    LOGGER,
    ProxmoxKeyAPIParse,
    ProxmoxType,
)
from .entity import ProxmoxEntity
from .models import ProxmoxEntityDescription


@dataclass
class ProxmoxSensorEntityDescription(ProxmoxEntityDescription, SensorEntityDescription):
    """Class describing Proxmox sensor entities."""

    conversion_fn: Callable | None = None  # conversion factor to be applied to units
    value_fn: Callable[[Any], bool | str] | None = None
    api_category: ProxmoxType | None = None  # Set when the sensor applies to only QEMU or LXC, if None applies to both.


PROXMOX_SENSOR_NODES: Final[tuple[ProxmoxSensorEntityDescription, ...]] = (
    ProxmoxSensorEntityDescription(
        key=ProxmoxKeyAPIParse.CPU,
        name="CPU used",
        icon="mdi:cpu-64-bit",
        native_unit_of_measurement=PERCENTAGE,
        conversion_fn=lambda x: (x * 100) if x > 0 else 0,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
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
    ),
    ProxmoxSensorEntityDescription(
        key=ProxmoxKeyAPIParse.MEMORY_FREE,
        name="Memory free",
        icon="mdi:memory",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
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
    ),
    ProxmoxSensorEntityDescription(
        key=ProxmoxKeyAPIParse.SWAP_FREE,
        name="Swap free",
        icon="mdi:memory",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
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
    ),
    ProxmoxSensorEntityDescription(
        key=ProxmoxKeyAPIParse.SWAP_TOTAL,
        name="Swap total",
        icon="mdi:memory",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        entity_registry_enabled_default=False,
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
    ),
    ProxmoxSensorEntityDescription(
        key=ProxmoxKeyAPIParse.UPTIME,
        name="Uptime",
        icon="mdi:database-clock-outline",
        conversion_fn=lambda x: (
            dt_util.utcnow() - timedelta(seconds=x) if x > 0 else None
        ),
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
)


PROXMOX_SENSOR_VM: Final[tuple[ProxmoxSensorEntityDescription, ...]] = (
    ProxmoxSensorEntityDescription(
        key="disk_free_perc",
        name="Disk free percentage",
        icon="mdi:harddisk",
        native_unit_of_measurement=PERCENTAGE,
        conversion_fn=lambda x: (x * 100) if x > 0 else 0,
        value_fn=lambda x: 1 - x.disk_used / x.disk_total if x.disk_total > 0 else 0,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    ProxmoxSensorEntityDescription(
        key=ProxmoxKeyAPIParse.DISK_TOTAL,
        name="Disk total",
        icon="mdi:harddisk-plus",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        entity_registry_enabled_default=False,
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
    ),
    ProxmoxSensorEntityDescription(
        key="disk_used_perc",
        name="Disk used percentage",
        icon="mdi:harddisk",
        native_unit_of_measurement=PERCENTAGE,
        conversion_fn=lambda x: (x * 100) if x > 0 else 0,
        value_fn=lambda x: x.disk_used / x.disk_total if x.disk_total > 0 else 0,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    ProxmoxSensorEntityDescription(
        key=ProxmoxKeyAPIParse.CPU,
        name="CPU used",
        icon="mdi:cpu-64-bit",
        native_unit_of_measurement=PERCENTAGE,
        conversion_fn=lambda x: (x * 100) if x >= 0 else 0,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    ProxmoxSensorEntityDescription(
        key=ProxmoxKeyAPIParse.MEMORY_FREE,
        name="Memory free",
        icon="mdi:memory",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
    ),
    ProxmoxSensorEntityDescription(
        key="memory_free_perc",
        name="Memory free percentage",
        icon="mdi:memory",
        native_unit_of_measurement=PERCENTAGE,
        conversion_fn=lambda x: (x * 100) if x > 0 else 0,
        value_fn=lambda x: x.memory_free / x.memory_total if x.memory_total > 0 else 0,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
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
    ),
    ProxmoxSensorEntityDescription(
        key="memory_used_perc",
        name="Memory used percentage",
        icon="mdi:memory",
        native_unit_of_measurement=PERCENTAGE,
        conversion_fn=lambda x: (x * 100) if x > 0 else 0,
        value_fn=lambda x: x.memory_used / x.memory_total if x.memory_total > 0 else 0,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
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
    ),
    ProxmoxSensorEntityDescription(
        key="node",
        name="Node",
        icon="mdi:server",
    ),
    ProxmoxSensorEntityDescription(
        key=ProxmoxKeyAPIParse.UPTIME,
        name="Uptime",
        icon="mdi:database-clock-outline",
        conversion_fn=lambda x: (
            dt_util.utcnow() - timedelta(seconds=x) if x > 0 else None
        ),
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
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
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor."""

    sensors = []

    coordinators = hass.data[DOMAIN][config_entry.entry_id][COORDINATORS]

    for node in config_entry.data[CONF_NODES]:
        coordinator = coordinators[node]
        # unfound vm case
        if coordinator.data is not None:
            for description in PROXMOX_SENSOR_NODES:
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
                        vm_id=None,
                        config_entry=config_entry,
                    )
                )

    for vm_id in config_entry.data[CONF_QEMU]:
        coordinator = coordinators[vm_id]
        # unfound vm case
        if coordinator.data is None:
            continue
        for description in PROXMOX_SENSOR_VM:
            if description.api_category in (None, ProxmoxType.QEMU):
                sensors.append(
                    create_sensor(
                        coordinator=coordinator,
                        info_device=device_info(
                            hass=hass,
                            config_entry=config_entry,
                            api_category=ProxmoxType.QEMU,
                            vm_id=vm_id,
                        ),
                        description=description,
                        vm_id=vm_id,
                        config_entry=config_entry,
                    )
                )

    for ct_id in config_entry.data[CONF_LXC]:
        coordinator = coordinators[ct_id]
        # unfound container case
        if coordinator.data is None:
            continue
        for description in PROXMOX_SENSOR_VM:
            if description.api_category in (None, ProxmoxType.LXC):
                sensors.append(
                    create_sensor(
                        coordinator=coordinator,
                        info_device=device_info(
                            hass=hass,
                            config_entry=config_entry,
                            api_category=ProxmoxType.LXC,
                            vm_id=ct_id,
                        ),
                        description=description,
                        vm_id=ct_id,
                        config_entry=config_entry,
                    )
                )

    async_add_entities(sensors)


def create_sensor(
    coordinator: DataUpdateCoordinator,
    info_device: DeviceInfo,
    description: ProxmoxSensorEntityDescription,
    config_entry: ConfigEntry,
    vm_id: str | None = None,
) -> ProxmoxSensorEntity:
    """Create a sensor based on the given data."""
    return ProxmoxSensorEntity(
        coordinator=coordinator,
        description=description,
        unique_id=f"{config_entry.entry_id}_{vm_id}_{description.key}",
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
            else:
                if self.entity_description.key is ProxmoxKeyAPIParse.CPU:
                    return 0
                else:
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
