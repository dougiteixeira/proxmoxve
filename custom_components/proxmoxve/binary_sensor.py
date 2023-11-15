"""Binary sensor to read Proxmox VE data."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from . import COORDINATORS, DOMAIN, device_info
from .const import CONF_LXC, CONF_NODES, CONF_QEMU, ProxmoxKeyAPIParse, ProxmoxType
from .entity import ProxmoxEntity
from .models import ProxmoxEntityDescription


@dataclass
class ProxmoxBinarySensorEntityDescription(
    ProxmoxEntityDescription, BinarySensorEntityDescription
):
    """Class describing Proxmox binarysensor entities."""

    on_value: Any | None = None
    inverted: bool | None = False
    api_category: ProxmoxType | None = None  # Set when the sensor applies to only QEMU or LXC, if None applies to both.


PROXMOX_BINARYSENSOR_NODES: Final[tuple[ProxmoxBinarySensorEntityDescription, ...]] = (
    ProxmoxBinarySensorEntityDescription(
        key=ProxmoxKeyAPIParse.STATUS,
        name="Status",
        device_class=BinarySensorDeviceClass.RUNNING,
        on_value="online",
        translation_key="status",
    ),
)

PROXMOX_BINARYSENSOR_UPDATES: Final[tuple[ProxmoxBinarySensorEntityDescription, ...]] = (
    ProxmoxBinarySensorEntityDescription(
        key=ProxmoxKeyAPIParse.UPDATE_AVAIL,
        name="Updates packages",
        device_class=BinarySensorDeviceClass.UPDATE,
        on_value=True,
        translation_key="update_avail",
    ),
)

PROXMOX_BINARYSENSOR_DISKS: Final[tuple[ProxmoxBinarySensorEntityDescription, ...]] = (
    ProxmoxBinarySensorEntityDescription(
        key=ProxmoxKeyAPIParse.HEALTH,
        name="Health",
        device_class=BinarySensorDeviceClass.PROBLEM,
        on_value="PASSED",
        inverted=True,
        translation_key="health",
    ),
)

PROXMOX_BINARYSENSOR_VM: Final[tuple[ProxmoxBinarySensorEntityDescription, ...]] = (
    ProxmoxBinarySensorEntityDescription(
        key=ProxmoxKeyAPIParse.STATUS,
        name="Status",
        device_class=BinarySensorDeviceClass.RUNNING,
        on_value="running",
        translation_key="status",
    ),
    ProxmoxBinarySensorEntityDescription(
        key=ProxmoxKeyAPIParse.HEALTH,
        name="Health",
        device_class=BinarySensorDeviceClass.PROBLEM,
        on_value="running",
        inverted=True,
        api_category=ProxmoxType.QEMU,
        translation_key="health",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors."""

    sensors = []
    coordinators = hass.data[DOMAIN][config_entry.entry_id][COORDINATORS]

    for node in config_entry.data[CONF_NODES]:
        if node in coordinators:
            coordinator = coordinators[node]
        else:
            continue

        # unfound node case
        if coordinator.data is not None:
            for description in PROXMOX_BINARYSENSOR_NODES:
                sensors.append(
                    create_binary_sensor(
                        coordinator=coordinator,
                        config_entry=config_entry,
                        info_device=device_info(
                            hass=hass,
                            config_entry=config_entry,
                            api_category=ProxmoxType.Node,
                            node=node,
                        ),
                        description=description,
                        resource_id=node,
                    )
                )

            if f"{ProxmoxType.Update}_{node}" in coordinators:
                coordinator_updates = coordinators[f"{ProxmoxType.Update}_{node}"]
                for description in PROXMOX_BINARYSENSOR_UPDATES:
                    sensors.append(
                        create_binary_sensor(
                            coordinator=coordinator_updates,
                            config_entry=config_entry,
                            info_device=device_info(
                                hass=hass,
                                config_entry=config_entry,
                                api_category=ProxmoxType.Update,
                                node=node,
                            ),
                            description=description,
                            resource_id=node,
                        )
                    )

            if f"{node}_{ProxmoxType.Disk}" in coordinators:
                for coordinator_disk in coordinators[f"{node}_{ProxmoxType.Disk}"]:
                    if (coordinator_data := coordinator_disk.data) is None:
                        continue

                    for description in PROXMOX_BINARYSENSOR_DISKS:
                        sensors.append(
                            create_binary_sensor(
                                coordinator=coordinator_disk,
                                info_device=device_info(
                                    hass=hass,
                                    config_entry=config_entry,
                                    api_category=ProxmoxType.Disk,
                                    node=node,
                                    resource_id=coordinator_data.path,
                                    cordinator_resource=coordinator_data,
                                ),
                                description=description,
                                resource_id=coordinator_data.path,
                                config_entry=config_entry,
                            )
                        )

    for vm_id in config_entry.data[CONF_QEMU]:
        if vm_id in coordinators:
            coordinator = coordinators[vm_id]
        else:
            continue

        # unfound vm case
        if coordinator.data is None:
            continue
        for description in PROXMOX_BINARYSENSOR_VM:
            if description.api_category in (None, ProxmoxType.QEMU):
                sensors.append(
                    create_binary_sensor(
                        coordinator=coordinator,
                        config_entry=config_entry,
                        info_device=device_info(
                            hass=hass,
                            config_entry=config_entry,
                            api_category=ProxmoxType.QEMU,
                            resource_id=vm_id,
                        ),
                        description=description,
                        resource_id=vm_id,
                    )
                )

    for container_id in config_entry.data[CONF_LXC]:
        if container_id in coordinators:
            coordinator = coordinators[container_id]
        else:
            continue

        # unfound container case
        if coordinator.data is None:
            continue
        for description in PROXMOX_BINARYSENSOR_VM:
            if description.api_category in (None, ProxmoxType.LXC):
                sensors.append(
                    create_binary_sensor(
                        coordinator=coordinator,
                        config_entry=config_entry,
                        info_device=device_info(
                            hass=hass,
                            config_entry=config_entry,
                            api_category=ProxmoxType.LXC,
                            resource_id=container_id,
                        ),
                        description=description,
                        resource_id=container_id,
                    )
                )

    async_add_entities(sensors)


def create_binary_sensor(
    coordinator,
    resource_id,
    config_entry,
    info_device,
    description,
) -> ProxmoxBinarySensorEntity:
    """Create a binary sensor based on the given data."""
    return ProxmoxBinarySensorEntity(
        coordinator=coordinator,
        unique_id=f"{config_entry.entry_id}_{resource_id}_{description.key}",
        description=description,
        info_device=info_device,
    )


class ProxmoxBinarySensorEntity(ProxmoxEntity, BinarySensorEntity):
    """A binary sensor for reading Proxmox VE data."""

    entity_description: ProxmoxBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        unique_id: str,
        info_device: DeviceInfo,
        description: ProxmoxBinarySensorEntityDescription,
    ) -> None:
        """Create the binary sensor for vms or containers."""
        super().__init__(coordinator, unique_id, description)

        self._attr_device_info = info_device

    @property
    def is_on(self) -> bool:
        """Return the state of the binary sensor."""
        if (data := self.coordinator.data) is None:
            return False

        if not getattr(data, self.entity_description.key):
            return False

        if self.entity_description.inverted:
            return (
                getattr(data, self.entity_description.key)
                != self.entity_description.on_value
            )
        return (
            getattr(data, self.entity_description.key)
            == self.entity_description.on_value
        )

    @property
    def available(self) -> bool:
        """Return sensor availability."""

        return super().available and self.coordinator.data is not None
