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
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from . import COORDINATORS, DOMAIN, async_migrate_old_unique_ids, device_info
from .const import CONF_LXC, CONF_NODES, CONF_QEMU, ProxmoxKeyAPIParse, ProxmoxType
from .entity import ProxmoxEntity, ProxmoxEntityDescription


@dataclass(frozen=True, kw_only=True)
class ProxmoxBinarySensorEntityDescription(
    ProxmoxEntityDescription, BinarySensorEntityDescription
):
    """Class describing Proxmox binarysensor entities."""

    on_value: list | None = None
    inverted: bool | None = False
    api_category: ProxmoxType | None = (
        None  # Set when the sensor applies to only QEMU or LXC, if None applies to both.
    )


PROXMOX_BINARYSENSOR_NODES: Final[tuple[ProxmoxBinarySensorEntityDescription, ...]] = (
    ProxmoxBinarySensorEntityDescription(
        key=ProxmoxKeyAPIParse.STATUS,
        name="Status",
        device_class=BinarySensorDeviceClass.RUNNING,
        on_value=["online"],
        translation_key="status",
    ),
)

PROXMOX_BINARYSENSOR_UPDATES: Final[
    tuple[ProxmoxBinarySensorEntityDescription, ...]
] = (
    ProxmoxBinarySensorEntityDescription(
        key=ProxmoxKeyAPIParse.UPDATE_AVAIL,
        name="Updates packages",
        device_class=BinarySensorDeviceClass.UPDATE,
        on_value=[True],
        translation_key="update_avail",
    ),
)

PROXMOX_BINARYSENSOR_DISKS: Final[tuple[ProxmoxBinarySensorEntityDescription, ...]] = (
    ProxmoxBinarySensorEntityDescription(
        key=ProxmoxKeyAPIParse.HEALTH,
        name="Health",
        device_class=BinarySensorDeviceClass.PROBLEM,
        on_value=["PASSED", "OK"],
        inverted=True,
        translation_key="health",
    ),
)

PROXMOX_BINARYSENSOR_VM: Final[tuple[ProxmoxBinarySensorEntityDescription, ...]] = (
    ProxmoxBinarySensorEntityDescription(
        key=ProxmoxKeyAPIParse.STATUS,
        name="Status",
        device_class=BinarySensorDeviceClass.RUNNING,
        on_value=["running"],
        translation_key="status",
    ),
    ProxmoxBinarySensorEntityDescription(
        key=ProxmoxKeyAPIParse.HEALTH,
        name="Health",
        device_class=BinarySensorDeviceClass.PROBLEM,
        on_value=["running"],
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

    async_add_entities(await async_setup_binary_sensors_nodes(hass, config_entry))
    async_add_entities(await async_setup_binary_sensors_qemu(hass, config_entry))
    async_add_entities(await async_setup_binary_sensors_lxc(hass, config_entry))


async def async_setup_binary_sensors_nodes(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> list:
    """Set up binary sensors."""

    sensors = []
    migrate_unique_id_disks = []

    coordinators = hass.data[DOMAIN][config_entry.entry_id][COORDINATORS]

    for node in config_entry.data[CONF_NODES]:
        if f"{ProxmoxType.Node}_{node}" in coordinators:
            coordinator = coordinators[f"{ProxmoxType.Node}_{node}"]
        else:
            continue

        # unfound node case
        if coordinator.data is not None:
            for description in PROXMOX_BINARYSENSOR_NODES:
                if getattr(coordinator.data, description.key, False):
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
                    if getattr(coordinator_updates.data, description.key, False):
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

            for coordinator_disk in coordinators.get(f"{ProxmoxType.Disk}_{node}", []):
                if (coordinator_data := coordinator_disk.data) is None:
                    continue

                for description in PROXMOX_BINARYSENSOR_DISKS:
                    if getattr(coordinator_disk.data, description.key, False):
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
                                resource_id=f"{node}_{coordinator_data.path}",
                                config_entry=config_entry,
                            )
                        )
                        migrate_unique_id_disks.append(
                            {
                                "old_unique_id": f"{config_entry.entry_id}_{coordinator_data.path}_{description.key}",
                                "new_unique_id": f"{config_entry.entry_id}_{node}_{coordinator_data.path}_{description.key}",
                            }
                        )

    await async_migrate_old_unique_ids(
        hass, Platform.BINARY_SENSOR, migrate_unique_id_disks
    )
    return sensors


async def async_setup_binary_sensors_qemu(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> list:
    """Set up binary sensors."""

    sensors = []

    coordinators = hass.data[DOMAIN][config_entry.entry_id][COORDINATORS]

    for vm_id in config_entry.data[CONF_QEMU]:
        if f"{ProxmoxType.QEMU}_{vm_id}" in coordinators:
            coordinator = coordinators[f"{ProxmoxType.QEMU}_{vm_id}"]
        else:
            continue

        # unfound vm case
        if coordinator.data is None:
            continue
        for description in PROXMOX_BINARYSENSOR_VM:
            if description.api_category in (None, ProxmoxType.QEMU):
                if getattr(coordinator.data, description.key, False):
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

    return sensors


async def async_setup_binary_sensors_lxc(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> list:
    """Set up binary sensors."""

    sensors = []

    coordinators = hass.data[DOMAIN][config_entry.entry_id][COORDINATORS]

    for container_id in config_entry.data[CONF_LXC]:
        if f"{ProxmoxType.LXC}_{container_id}" in coordinators:
            coordinator = coordinators[f"{ProxmoxType.LXC}_{container_id}"]
        else:
            continue

        # unfound container case
        if coordinator.data is None:
            continue
        for description in PROXMOX_BINARYSENSOR_VM:
            if description.api_category in (None, ProxmoxType.LXC):
                if getattr(coordinator.data, description.key, False):
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

    return sensors


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
                not in self.entity_description.on_value
            )
        return (
            getattr(data, self.entity_description.key)
            in self.entity_description.on_value
        )

    @property
    def available(self) -> bool:
        """Return sensor availability."""

        return super().available and self.coordinator.data is not None
