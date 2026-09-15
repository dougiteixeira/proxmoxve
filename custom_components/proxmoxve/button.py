# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Button to set Proxmox VE data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription

from . import device_info
from .api import ProxmoxClient, post_api_command
from .const import (
    CONF_LXC,
    CONF_NODES,
    CONF_QEMU,
    COORDINATORS,
    LOGGER,
    PROXMOX_CLIENT,
    PROXMOX_HA_ADMIN_CLIENT,
    PROXMOX_HA_ADMIN_PERMISSIONS,
    PROXMOX_PERMISSIONS,
    RESOURCE_CALLBACKS,
    ProxmoxCommand,
    ProxmoxType,
)
from .discovery import selected
from .entity import ProxmoxEntity, ProxmoxEntityDescription
from .permissions import (
    Permissions,
    ProxmoxPrivilege,
    is_granted,
    is_granted_anywhere_below,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.device_registry import DeviceInfo
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
    from homeassistant.helpers.update_coordinator import DataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class ProxmoxButtonEntityDescription(ProxmoxEntityDescription, ButtonEntityDescription):
    """Class describing Proxmox buttons entities."""

    api_category: ProxmoxType | None = (
        None  # Set when the sensor applies to only QEMU or LXC, if None applies to both.
    )
    # The privilege Proxmox checks for this action. The button is left out
    # when the credentials are known not to hold it; see button_permitted().
    privilege: ProxmoxPrivilege | None = None


# The node actions that act on guests rather than on the node: Proxmox
# checks VM.PowerMgmt per guest for these, not Sys.PowerMgmt on the node.
BULK_GUEST_COMMANDS: Final[frozenset[ProxmoxCommand]] = frozenset(
    {ProxmoxCommand.START_ALL, ProxmoxCommand.STOP_ALL, ProxmoxCommand.SUSPEND_ALL}
)


def button_permitted(
    permissions: Permissions | None,
    description: ProxmoxButtonEntityDescription,
    api_category: ProxmoxType,
    resource_id: str | int,
) -> bool:
    """
    Return whether the credentials can perform a button's action.

    Unknown permissions (None) permit everything: not knowing is not the
    same as not being allowed, and a failed press still raises a repair
    issue naming the privilege. A description without a privilege is not
    gated either.
    """
    if permissions is None or description.privilege is None:
        return True

    if api_category is ProxmoxType.Proxmox:
        return is_granted(permissions, "/", description.privilege)
    if api_category is ProxmoxType.Node:
        if description.key in BULK_GUEST_COMMANDS:
            # `startall` starts every guest the credentials may start, so a
            # grant on a single guest is enough for the button to do something.
            return is_granted_anywhere_below(permissions, "/vms", description.privilege)
        return is_granted(permissions, f"/nodes/{resource_id}", description.privilege)
    return is_granted(permissions, f"/vms/{resource_id}", description.privilege)


PROXMOX_BUTTON_NODE: Final[tuple[ProxmoxButtonEntityDescription, ...]] = (
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.START_ALL,
        privilege=ProxmoxPrivilege.VM_POWER,
        icon="mdi:play",
        name="Start all",
        entity_registry_enabled_default=False,
        translation_key="start_all",
    ),
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.STOP_ALL,
        privilege=ProxmoxPrivilege.VM_POWER,
        icon="mdi:stop",
        name="Stop all",
        entity_registry_enabled_default=False,
        translation_key="stop_all",
    ),
    # Suspends every running VM to disk (`qm suspend --todisk`); containers
    # cannot be suspended and are left alone. The counterpart of "Start all"
    # before a planned power-off, when a clean shutdown of each guest would
    # take too long or lose too much.
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.SUSPEND_ALL,
        privilege=ProxmoxPrivilege.VM_POWER,
        icon="mdi:pause-circle-outline",
        name="Suspend all",
        entity_registry_enabled_default=False,
        translation_key="suspend_all",
    ),
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.SHUTDOWN,
        privilege=ProxmoxPrivilege.SYS_POWER,
        icon="mdi:server-off",
        name="Shutdown",
        entity_registry_enabled_default=False,
        translation_key="shutdown",
    ),
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.REBOOT,
        privilege=ProxmoxPrivilege.SYS_POWER,
        icon="mdi:restart",
        name="Reboot",
        entity_registry_enabled_default=False,
        translation_key="reboot",
    ),
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.WAKEONLAN,
        privilege=ProxmoxPrivilege.SYS_POWER,
        icon="mdi:play-network",
        name="Wake-on-LAN",
        entity_registry_enabled_default=False,
        translation_key="wakeonlan",
    ),
)

PROXMOX_BUTTON_VM: Final[tuple[ProxmoxButtonEntityDescription, ...]] = (
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.REBOOT,
        privilege=ProxmoxPrivilege.VM_POWER,
        icon="mdi:restart",
        name="Reboot",
        entity_registry_enabled_default=False,
        translation_key="reboot",
    ),
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.START,
        privilege=ProxmoxPrivilege.VM_POWER,
        icon="mdi:server",
        name="Start",
        entity_registry_enabled_default=False,
        translation_key="start",
    ),
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.SHUTDOWN,
        privilege=ProxmoxPrivilege.VM_POWER,
        icon="mdi:server-off",
        name="Shutdown",
        entity_registry_enabled_default=False,
        translation_key="shutdown",
    ),
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.STOP,
        privilege=ProxmoxPrivilege.VM_POWER,
        icon="mdi:stop",
        name="Stop",
        entity_registry_enabled_default=False,
        translation_key="stop",
    ),
    # Needs VM.Snapshot rather than VM.PowerMgmt; the snapshot is named
    # after the moment it was taken, see snapshot_name() in api.py.
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.SNAPSHOT,
        privilege=ProxmoxPrivilege.VM_SNAPSHOT,
        icon="mdi:camera-outline",
        name="Create snapshot",
        entity_registry_enabled_default=False,
        translation_key="snapshot",
    ),
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.UNLOCK,
        privilege=ProxmoxPrivilege.VM_CONFIG_OPTIONS,
        icon="mdi:lock-open",
        name="Unlock",
        # QEMU only: the LXC config API has no way to clear a lock
        # (no skiplock parameter), so `pct unlock` on the node is the only
        # option for containers. Unlock a VM needs root@pam (not a token).
        api_category=ProxmoxType.QEMU,
        entity_registry_enabled_default=False,
        translation_key="unlock",
    ),
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.RESUME,
        privilege=ProxmoxPrivilege.VM_POWER,
        icon="mdi:play",
        name="Resume",
        api_category=ProxmoxType.QEMU,
        entity_registry_enabled_default=False,
        translation_key="resume",
    ),
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.SUSPEND,
        privilege=ProxmoxPrivilege.VM_POWER,
        icon="mdi:pause",
        name="Suspend",
        api_category=ProxmoxType.QEMU,
        entity_registry_enabled_default=False,
        translation_key="suspend",
    ),
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.HIBERNATE,
        privilege=ProxmoxPrivilege.VM_POWER,
        icon="mdi:bed",
        name="Hibernate",
        api_category=ProxmoxType.QEMU,
        entity_registry_enabled_default=False,
        translation_key="hibernate",
    ),
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.RESET,
        privilege=ProxmoxPrivilege.VM_POWER,
        icon="mdi:restart-alert",
        name="Reset",
        api_category=ProxmoxType.QEMU,
        entity_registry_enabled_default=False,
        translation_key="reset",
    ),
)

PROXMOX_BUTTON_CLUSTER: Final[tuple[ProxmoxButtonEntityDescription, ...]] = (
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.DISARM_HA,
        privilege=ProxmoxPrivilege.SYS_CONSOLE,
        icon="mdi:shield-off-outline",
        name="Disarm HA",
        entity_registry_enabled_default=False,
        translation_key="disarm_ha",
    ),
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.ARM_HA,
        privilege=ProxmoxPrivilege.SYS_CONSOLE,
        icon="mdi:shield-check-outline",
        name="Arm HA",
        entity_registry_enabled_default=False,
        translation_key="arm_ha",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up button."""
    async_add_entities(
        [
            *await async_setup_buttons_nodes(hass, config_entry),
            *await async_setup_buttons_guests(hass, config_entry, ProxmoxType.QEMU),
            *await async_setup_buttons_guests(hass, config_entry, ProxmoxType.LXC),
            *await async_setup_buttons_cluster(hass, config_entry),
        ]
    )

    async def _async_add_resource(api_category: ProxmoxType, resource_id: str) -> None:
        """Build the buttons of a resource discovery found at runtime."""
        if api_category is ProxmoxType.Node:
            async_add_entities(
                await async_setup_buttons_nodes(hass, config_entry, [resource_id])
            )
        elif api_category in (ProxmoxType.QEMU, ProxmoxType.LXC):
            async_add_entities(
                await async_setup_buttons_guests(
                    hass, config_entry, api_category, [resource_id]
                )
            )

    config_entry.runtime_data[RESOURCE_CALLBACKS].append(_async_add_resource)


async def async_setup_buttons_nodes(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    only: list[str] | None = None,
) -> list:
    """Build the buttons of the given nodes, or of all tracked ones."""
    buttons = []
    coordinators = config_entry.runtime_data[COORDINATORS]
    proxmox_client = config_entry.runtime_data[PROXMOX_CLIENT]
    permissions = config_entry.runtime_data.get(PROXMOX_PERMISSIONS)

    for node in selected(config_entry, CONF_NODES, only):
        if f"{ProxmoxType.Node}_{node}" in coordinators:
            coordinator = coordinators[f"{ProxmoxType.Node}_{node}"]
        else:
            continue

        # unfound node case
        if coordinator.data is None:
            continue
        for description in PROXMOX_BUTTON_NODE:
            if not button_permitted(permissions, description, ProxmoxType.Node, node):
                LOGGER.debug(
                    "Leaving out the %s button of node %s: no %s",
                    description.key,
                    node,
                    description.privilege,
                )
                continue
            buttons.append(
                create_button(
                    coordinator=coordinator,
                    info_device=device_info(
                        hass=hass,
                        config_entry=config_entry,
                        api_category=ProxmoxType.Node,
                        node=node,
                    ),
                    description=description,
                    resource_id=node,
                    proxmox_client=proxmox_client,
                    api_category=ProxmoxType.Node,
                    config_entry=config_entry,
                )
            )

    return buttons


async def async_setup_buttons_guests(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    api_category: ProxmoxType,
    only: list[str] | None = None,
) -> list:
    """Build the buttons of the given VMs or containers, or of all tracked ones."""
    buttons = []
    coordinators = config_entry.runtime_data[COORDINATORS]
    proxmox_client = config_entry.runtime_data[PROXMOX_CLIENT]
    permissions = config_entry.runtime_data.get(PROXMOX_PERMISSIONS)
    key = CONF_QEMU if api_category is ProxmoxType.QEMU else CONF_LXC

    for vm_id in selected(config_entry, key, only):
        if f"{api_category}_{vm_id}" in coordinators:
            coordinator = coordinators[f"{api_category}_{vm_id}"]
        else:
            continue

        # unfound guest case
        if coordinator.data is None:
            continue
        for description in PROXMOX_BUTTON_VM:
            if (
                description.api_category is not None
                and api_category not in description.api_category
            ):
                continue
            if not button_permitted(permissions, description, api_category, vm_id):
                LOGGER.debug(
                    "Leaving out the %s button of %s %s: no %s",
                    description.key,
                    api_category.upper(),
                    vm_id,
                    description.privilege,
                )
                continue
            buttons.append(
                create_button(
                    coordinator=coordinator,
                    info_device=device_info(
                        hass=hass,
                        config_entry=config_entry,
                        api_category=api_category,
                        resource_id=vm_id,
                    ),
                    description=description,
                    resource_id=vm_id,
                    proxmox_client=proxmox_client,
                    api_category=api_category,
                    config_entry=config_entry,
                )
            )

    return buttons


async def async_setup_buttons_cluster(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> list:
    """Build the cluster-wide HA buttons, when the cluster credentials allow."""
    buttons = []
    coordinators = config_entry.runtime_data[COORDINATORS]
    proxmox_ha_admin_client = config_entry.runtime_data.get(PROXMOX_HA_ADMIN_CLIENT)
    ha_admin_permissions = config_entry.runtime_data.get(PROXMOX_HA_ADMIN_PERMISSIONS)
    ha_resources_coordinator = coordinators.get(f"{ProxmoxType.Proxmox}_ha_resources")
    if proxmox_ha_admin_client is None or ha_resources_coordinator is None:
        return buttons

    for description in PROXMOX_BUTTON_CLUSTER:
        if not button_permitted(
            ha_admin_permissions, description, ProxmoxType.Proxmox, "cluster"
        ):
            LOGGER.debug(
                "Leaving out the %s button: the cluster credentials have no %s",
                description.key,
                description.privilege,
            )
            continue
        buttons.append(
            create_button(
                coordinator=ha_resources_coordinator,
                info_device=device_info(
                    hass=hass,
                    config_entry=config_entry,
                    api_category=ProxmoxType.Proxmox,
                ),
                description=description,
                resource_id="cluster",
                proxmox_client=proxmox_ha_admin_client,
                api_category=ProxmoxType.Proxmox,
                config_entry=config_entry,
            )
        )

    return buttons


def create_button(
    *,
    coordinator: DataUpdateCoordinator,
    info_device: DeviceInfo,
    description: ProxmoxButtonEntityDescription,
    proxmox_client: ProxmoxClient,
    api_category: ProxmoxType,
    resource_id: str | int,
    config_entry: ConfigEntry,
) -> ProxmoxButtonEntity:
    """Create a button based on the given data."""
    return ProxmoxButtonEntity(
        description=description,
        proxmox_client=proxmox_client,
        api_category=api_category,
        coordinator=coordinator,
        unique_id=f"{config_entry.entry_id}_{resource_id}_{description.key}",
        resource_id=resource_id,
        info_device=info_device,
        config_entry=config_entry,
    )


class ProxmoxButtonEntity(ProxmoxEntity, ButtonEntity):
    """A button for reading/writing Proxmox VE status."""

    entity_description: ProxmoxButtonEntityDescription

    def __init__(
        self,
        *,
        coordinator: DataUpdateCoordinator,
        info_device: DeviceInfo,
        description: ProxmoxButtonEntityDescription,
        unique_id: str,
        proxmox_client: ProxmoxClient,
        api_category: ProxmoxType,
        resource_id: str | int,
        config_entry: ConfigEntry,
    ) -> None:
        """Create the button for vms or containers."""
        super().__init__(coordinator, unique_id, description)

        self._attr_device_info = info_device
        self.config_entry = config_entry

        def _button_press() -> None:
            """Post start command & tell HA state is on."""
            if api_category == ProxmoxType.Proxmox:
                # Cluster-wide HA arm/disarm; not tied to a node or guest.
                node = None
                vm_id = None
            elif api_category == ProxmoxType.Node:
                node = resource_id
                vm_id = None
            else:
                if (data := self.coordinator.data) is None:
                    return
                node = data.node
                vm_id = resource_id

            result = post_api_command(
                self,
                proxmox_client=proxmox_client,
                node=node,
                vm_id=vm_id,
                api_category=api_category,
                command=description.key,
            )

            LOGGER.debug(
                "Button press: %s - %s - %s - %s: %s",
                node,
                vm_id,
                api_category,
                description.key,
                result,
            )

        self._button_press_funct = _button_press

    @property
    def available(self) -> bool:
        """Return sensor availability."""
        return super().available and self.coordinator.data is not None

    def press(self) -> None:
        """Press the button."""
        self._button_press_funct()
