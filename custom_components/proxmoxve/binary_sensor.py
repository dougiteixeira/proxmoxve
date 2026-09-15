# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Binary sensor to read Proxmox VE data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import Platform
from homeassistant.helpers.typing import UNDEFINED

from . import COORDINATORS, async_migrate_old_unique_ids, device_info
from .const import (
    CONF_LXC,
    CONF_NODES,
    CONF_QEMU,
    ProxmoxKeyAPIParse,
    ProxmoxType,
)
from .entity import ProxmoxEntity, ProxmoxEntityDescription

if TYPE_CHECKING:
    from collections.abc import Mapping

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.device_registry import DeviceInfo
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
    from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

    from .coordinator import ProxmoxHAResourcesCoordinator


@dataclass(frozen=True, kw_only=True)
class ProxmoxBinarySensorEntityDescription(
    ProxmoxEntityDescription, BinarySensorEntityDescription
):
    """Class describing Proxmox binarysensor entities."""

    on_value: list | None = None
    inverted: bool | None = False
    extra_attrs: list[str] | None = None
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
    ProxmoxBinarySensorEntityDescription(
        key=ProxmoxKeyAPIParse.LOCKED,
        name="Locked",
        on_value=[True],
        translation_key="locked",
    ),
)

PROXMOX_BINARYSENSOR_HA_MANAGED: Final[ProxmoxBinarySensorEntityDescription] = (
    ProxmoxBinarySensorEntityDescription(
        key="ha_managed",
        name="HA managed",
        translation_key="ha_managed",
    )
)


PROXMOX_BINARYSENSOR_HA_STATUS: Final[
    tuple[ProxmoxBinarySensorEntityDescription, ...]
] = (
    ProxmoxBinarySensorEntityDescription(
        key="quorate",
        name="Quorate",
        icon="mdi:check-network-outline",
        on_value=[True],
        translation_key="cluster_quorate",
    ),
    # Carries the CRM master's liveness instead of a "last seen" timestamp:
    # the CRM refreshes that timestamp every few seconds, so a timestamp
    # sensor writes a new state on every poll, while this one only changes
    # when the master actually goes missing.
    ProxmoxBinarySensorEntityDescription(
        key="crm_master_stale",
        name="CRM master stale",
        icon="mdi:crown-outline",
        device_class=BinarySensorDeviceClass.PROBLEM,
        on_value=[True],
        translation_key="ha_crm_master_stale",
    ),
)


PROXMOX_BINARYSENSOR_REPLICATION: Final[
    tuple[ProxmoxBinarySensorEntityDescription, ...]
] = (
    ProxmoxBinarySensorEntityDescription(
        key="failing",
        name="Replication failing",
        icon="mdi:folder-alert-outline",
        device_class=BinarySensorDeviceClass.PROBLEM,
        on_value=[True],
        entity_registry_enabled_default=False,
        extra_attrs=["failing_jobs", "jobs"],
        translation_key="replication_failing",
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
    async_add_entities(await async_setup_binary_sensors_ha_status(hass, config_entry))
    async_add_entities(await async_setup_binary_sensors_replication(hass, config_entry))


async def async_setup_binary_sensors_ha_status(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> list:
    """Set up the cluster HA status binary sensors."""
    coordinators = config_entry.runtime_data[COORDINATORS]

    # Only present when the optional cluster HA administration credentials
    # are configured and could be authenticated.
    if (
        coordinator := coordinators.get(f"{ProxmoxType.Proxmox}_ha_status")
    ) is None or coordinator.data is None:
        return []

    return [
        create_binary_sensor(
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
        for description in PROXMOX_BINARYSENSOR_HA_STATUS
        if getattr(coordinator.data, description.key, UNDEFINED) is not UNDEFINED
    ]


async def async_setup_binary_sensors_replication(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> list:
    """Set up the per-node replication binary sensors."""
    coordinators = config_entry.runtime_data[COORDINATORS]
    sensors = []

    for node in config_entry.data[CONF_NODES]:
        coordinator = coordinators.get(f"{ProxmoxType.Replication}_{node}")
        # A node with no replication jobs gets no entity at all.
        if coordinator is None or coordinator.data is None or not coordinator.data.jobs:
            continue

        sensors.extend(
            create_binary_sensor(
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
            for description in PROXMOX_BINARYSENSOR_REPLICATION
        )

    return sensors


async def async_setup_binary_sensors_nodes(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> list:
    """Set up binary sensors."""
    sensors = []
    migrate_unique_id_disks = []

    coordinators = config_entry.runtime_data[COORDINATORS]

    for node in config_entry.data[CONF_NODES]:
        if f"{ProxmoxType.Node}_{node}" in coordinators:
            coordinator = coordinators[f"{ProxmoxType.Node}_{node}"]
        else:
            continue

        # unfound node case
        if coordinator.data is not None:
            for description in PROXMOX_BINARYSENSOR_NODES:
                if getattr(coordinator.data, description.key, UNDEFINED) != UNDEFINED:
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
                    if (
                        getattr(coordinator_updates.data, description.key, False)
                        != UNDEFINED
                    ):
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
                        migrate_unique_id_disks.append(
                            {
                                "old_unique_id": f"{config_entry.entry_id}_{coordinator_data.path}_{description.key}",
                                "new_unique_id": f"{config_entry.entry_id}_{node}_{coordinator_data.disk_id}_{description.key}",
                            }
                        )
                        migrate_unique_id_disks.append(
                            {
                                "old_unique_id": f"{config_entry.entry_id}_{node}_{coordinator_data.path}_{description.key}",
                                "new_unique_id": f"{config_entry.entry_id}_{node}_{coordinator_data.disk_id}_{description.key}",
                            }
                        )
                        if (
                            coordinator_data.wwn
                            and coordinator_data.wwn != coordinator_data.disk_id
                        ):
                            migrate_unique_id_disks.append(
                                {
                                    "old_unique_id": f"{config_entry.entry_id}_{node}_{coordinator_data.wwn}_{description.key}",
                                    "new_unique_id": f"{config_entry.entry_id}_{node}_{coordinator_data.disk_id}_{description.key}",
                                }
                            )
                        await async_migrate_old_unique_ids(
                            hass, Platform.BINARY_SENSOR, migrate_unique_id_disks
                        )

                        sensors.append(
                            create_binary_sensor(
                                coordinator=coordinator_disk,
                                info_device=device_info(
                                    hass=hass,
                                    config_entry=config_entry,
                                    api_category=ProxmoxType.Disk,
                                    node=node,
                                    resource_id=coordinator_data.disk_id,
                                    cordinator_resource=coordinator_data,
                                ),
                                description=description,
                                resource_id=f"{node}_{coordinator_data.disk_id}",
                                config_entry=config_entry,
                            )
                        )
    return sensors


async def async_setup_binary_sensors_qemu(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> list:
    """Set up binary sensors."""
    sensors = []

    coordinators = config_entry.runtime_data[COORDINATORS]
    ha_resources_coordinator = coordinators.get(f"{ProxmoxType.Proxmox}_ha_resources")

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
                if getattr(coordinator.data, description.key, UNDEFINED) != UNDEFINED:
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

        if ha_resources_coordinator is not None:
            sensors.append(
                ProxmoxHAManagedBinarySensorEntity(
                    coordinator=ha_resources_coordinator,
                    unique_id=f"{config_entry.entry_id}_{vm_id}_ha_managed",
                    info_device=device_info(
                        hass=hass,
                        config_entry=config_entry,
                        api_category=ProxmoxType.QEMU,
                        resource_id=vm_id,
                    ),
                    description=PROXMOX_BINARYSENSOR_HA_MANAGED,
                    sid=f"vm:{vm_id}",
                )
            )

    return sensors


async def async_setup_binary_sensors_lxc(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> list:
    """Set up binary sensors."""
    sensors = []

    coordinators = config_entry.runtime_data[COORDINATORS]
    ha_resources_coordinator = coordinators.get(f"{ProxmoxType.Proxmox}_ha_resources")

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
                if getattr(coordinator.data, description.key, UNDEFINED) != UNDEFINED:
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

        if ha_resources_coordinator is not None:
            sensors.append(
                ProxmoxHAManagedBinarySensorEntity(
                    coordinator=ha_resources_coordinator,
                    unique_id=f"{config_entry.entry_id}_{container_id}_ha_managed",
                    info_device=device_info(
                        hass=hass,
                        config_entry=config_entry,
                        api_category=ProxmoxType.LXC,
                        resource_id=container_id,
                    ),
                    description=PROXMOX_BINARYSENSOR_HA_MANAGED,
                    sid=f"ct:{container_id}",
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

        if not (data_value := getattr(data, self.entity_description.key)):
            return False

        if self.entity_description.inverted:
            return data_value not in self.entity_description.on_value

        return data_value in self.entity_description.on_value

    @property
    def available(self) -> bool:
        """Return sensor availability."""
        return super().available and self.coordinator.data is not None

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return the extra attributes of the binary sensor."""
        if self.entity_description.extra_attrs is None:
            return None

        if (data := self.coordinator.data) is None:
            return None

        return {
            attr: getattr(data, attr, False)
            for attr in self.entity_description.extra_attrs
        }


class ProxmoxHAManagedBinarySensorEntity(ProxmoxEntity, BinarySensorEntity):
    """
    Whether a guest is managed by the Proxmox HA stack.

    Backed by the shared ProxmoxHAResourcesCoordinator (a set of resource
    sids) rather than a per-guest coordinator, so `is_on` checks membership
    directly instead of the generic `getattr(data, key)` lookup the other
    binary sensors use.
    """

    entity_description: ProxmoxBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: ProxmoxHAResourcesCoordinator,
        unique_id: str,
        info_device: DeviceInfo,
        description: ProxmoxBinarySensorEntityDescription,
        sid: str,
    ) -> None:
        """Create the HA-managed binary sensor for a VM or container."""
        super().__init__(coordinator, unique_id, description)

        self._attr_device_info = info_device
        self._sid = sid

    @property
    def is_on(self) -> bool:
        """Return whether this guest's sid is in the HA-managed resources."""
        if (data := self.coordinator.data) is None:
            return False
        return self._sid in data

    @property
    def available(self) -> bool:
        """Return sensor availability."""
        return super().available and self.coordinator.data is not None
