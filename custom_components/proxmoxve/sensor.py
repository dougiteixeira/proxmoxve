"""Sensor to read Proxmox VE data."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import timedelta
from typing import Final
from collections.abc import Callable

import homeassistant.util.dt as dt_util

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_TIME,
    CONF_HOST,
    CONF_PORT,
    DATA_GIGABYTES,
    DATA_MEGABYTES,
    PERCENTAGE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from . import ProxmoxEntity, device_info
from .const import (
    CONF_LXC,
    CONF_NODE,
    CONF_QEMU,
    COORDINATORS,
    DOMAIN,
    ProxmoxType,
)


@dataclass
class ProxmoxSensorDescription(SensorEntityDescription):
    """Class describing Proxmox sensor entities."""

    unit_metric: str | None = None
    unit_imperial: str | None = None
    conversion: Callable | None = None  # conversion factor to be applied to units
    value: Callable = lambda x: x


PROXMOX_SENSOR_NODES: Final[tuple[ProxmoxSensorDescription, ...]] = (
    ProxmoxSensorDescription(
        key="uptime",
        name="Uptime",
        icon="mdi:database-clock-outline",
        unit_metric=ATTR_TIME,
        unit_imperial=ATTR_TIME,
        conversion=lambda x: (
            dt_util.utcnow() - timedelta(seconds=x) if x > 0 else None
        ),
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    ProxmoxSensorDescription(
        key="cpu",
        name="CPU used",
        icon="mdi:cpu-64-bit",
        unit_metric=PERCENTAGE,
        unit_imperial=PERCENTAGE,
        native_unit_of_measurement=PERCENTAGE,
        conversion=lambda x: round(x * 100, 1),
        state_class=SensorStateClass.MEASUREMENT,
    ),
    ProxmoxSensorDescription(
        key="memory_used",
        name="Memory used",
        icon="mdi:memory",
        native_unit_of_measurement=DATA_GIGABYTES,
        conversion=lambda x: round(x / 1073741824, 2),
        state_class=SensorStateClass.MEASUREMENT,
    ),
    ProxmoxSensorDescription(
        key="memory_free",
        name="Memory free",
        icon="mdi:memory",
        native_unit_of_measurement=DATA_GIGABYTES,
        conversion=lambda x: round(x / 1073741824, 2),
        state_class=SensorStateClass.MEASUREMENT,
    ),
    ProxmoxSensorDescription(
        key="memory_total",
        name="Memory total",
        icon="mdi:memory",
        native_unit_of_measurement=DATA_GIGABYTES,
        conversion=lambda x: round(x / 1073741824, 2),
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=True,
    ),
    ProxmoxSensorDescription(
        key="swap_total",
        name="Swap total",
        icon="mdi:memory",
        native_unit_of_measurement=DATA_GIGABYTES,
        conversion=lambda x: round(x / 1073741824, 2),
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=True,
    ),
    ProxmoxSensorDescription(
        key="swap_free",
        name="Swap free",
        icon="mdi:memory",
        native_unit_of_measurement=DATA_GIGABYTES,
        conversion=lambda x: round(x / 1073741824, 2),
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=True,
    ),
    ProxmoxSensorDescription(
        key="cal_memory_free",
        name="Memory free percentage",
        icon="mdi:memory",
        unit_metric=PERCENTAGE,
        unit_imperial=PERCENTAGE,
        native_unit_of_measurement=PERCENTAGE,
        conversion=lambda x: round(x * 100, 1),
        value=lambda x: 1 - x["memory_used"] / x["memory_total"],
        state_class=SensorStateClass.MEASUREMENT,
    ),
)


PROXMOX_SENSOR_VM: Final[tuple[ProxmoxSensorDescription, ...]] = (
    ProxmoxSensorDescription(
        key="uptime",
        name="Uptime",
        icon="mdi:database-clock-outline",
        unit_metric=ATTR_TIME,
        unit_imperial=ATTR_TIME,
        conversion=lambda x: (
            dt_util.utcnow() - timedelta(seconds=x) if x > 0 else None
        ),
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    ProxmoxSensorDescription(
        key="disk_used",
        name="Disk used",
        icon="mdi:harddisk",
        native_unit_of_measurement=DATA_GIGABYTES,
        conversion=lambda x: round(x / 1073741824, 2),
        state_class=SensorStateClass.MEASUREMENT,
    ),
    ProxmoxSensorDescription(
        key="disk_total",
        name="Disk total",
        icon="mdi:harddisk-plus",
        native_unit_of_measurement=DATA_GIGABYTES,
        conversion=lambda x: round(x / 1073741824, 2),
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=True,
    ),
    ProxmoxSensorDescription(
        key="calc_disk_free",
        name="Disk free percentage",
        icon="mdi:harddisk",
        unit_metric=PERCENTAGE,
        unit_imperial=PERCENTAGE,
        native_unit_of_measurement=PERCENTAGE,
        conversion=lambda x: round(x * 100, 1),
        value=lambda x: 1 - x["disk_used"] / x["disk_total"],
        state_class=SensorStateClass.MEASUREMENT,
    ),
    ProxmoxSensorDescription(
        key="cpu",
        name="CPU used",
        icon="mdi:cpu-64-bit",
        unit_metric=PERCENTAGE,
        unit_imperial=PERCENTAGE,
        native_unit_of_measurement=PERCENTAGE,
        conversion=lambda x: round(x * 100, 1),
        state_class=SensorStateClass.MEASUREMENT,
    ),
    ProxmoxSensorDescription(
        key="memory_used",
        name="Memory used",
        icon="mdi:memory",
        native_unit_of_measurement=DATA_GIGABYTES,
        conversion=lambda x: round(x / 1073741824, 2),
        state_class=SensorStateClass.MEASUREMENT,
    ),
    ProxmoxSensorDescription(
        key="memory_free",
        name="Memory free",
        icon="mdi:memory",
        native_unit_of_measurement=DATA_GIGABYTES,
        conversion=lambda x: round(x / 1073741824, 2),
        state_class=SensorStateClass.MEASUREMENT,
    ),
    ProxmoxSensorDescription(
        key="memory_total",
        name="Memory total",
        icon="mdi:memory",
        native_unit_of_measurement=DATA_GIGABYTES,
        conversion=lambda x: round(x / 1073741824, 2),
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=True,
    ),
    ProxmoxSensorDescription(
        key="cal_memory_free",
        name="Memory free percentage",
        icon="mdi:memory",
        unit_metric=PERCENTAGE,
        unit_imperial=PERCENTAGE,
        native_unit_of_measurement=PERCENTAGE,
        conversion=lambda x: round(x * 100, 1),
        value=lambda x: 1 - x["memory_used"] / x["memory_total"],
        state_class=SensorStateClass.MEASUREMENT,
    ),
    ProxmoxSensorDescription(
        key="network_in",
        name="Network in",
        icon="mdi:download-network-outline",
        native_unit_of_measurement=DATA_MEGABYTES,
        conversion=lambda x: round(x / 1048576, 2),
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=True,
    ),
    ProxmoxSensorDescription(
        key="network_out",
        name="Network out",
        icon="mdi:upload-network-outline",
        native_unit_of_measurement=DATA_MEGABYTES,
        conversion=lambda x: round(x / 1048576, 2),
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=True,
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

    coordinator = coordinators[ProxmoxType.Node]
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
                        vm_id=None,
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
    description: ProxmoxSensorDescription,
    vm_id: str,
    config_entry,
):
    """Create a sensor based on the given data."""
    return ProxmoxSensor(
        coordinator=coordinator,
        description=description,
        unique_id=f"proxmox_{config_entry.data[CONF_HOST]}_{config_entry.data[CONF_PORT]}_{config_entry.data[CONF_NODE]}_{vm_id}_{description.key}",
        info_device=info_device,
    )


class ProxmoxSensor(ProxmoxEntity, SensorEntity):
    """A sensor for reading Proxmox VE data."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        info_device: DeviceInfo,
        description: ProxmoxSensorDescription,
        unique_id: str,
    ) -> None:
        """Create the button for vms or containers."""
        super().__init__(coordinator, unique_id, description.name, description.icon)

        self._attr_device_info = info_device
        self.entity_description = description

    @property
    def native_value(self):
        """Return the units of the sensor."""
        if (data := self.coordinator.data) is None:
            return None

        if self.entity_description.key not in data:
            if self.entity_description.value is not None:
                native_value = self.entity_description.value(data)
            else:
                return None
        else:
            native_value = data[self.entity_description.key]

        if self.entity_description.conversion is not None:
            return self.entity_description.conversion(native_value)

        return native_value

    @property
    def available(self):
        """Return sensor availability."""

        return super().available and self.coordinator.data is not None
