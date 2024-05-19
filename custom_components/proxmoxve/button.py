"""Button to set Proxmox VE data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from . import device_info
from .api import ProxmoxClient, post_api_command
from .const import (
    CONF_LXC,
    CONF_NODES,
    CONF_QEMU,
    COORDINATORS,
    DOMAIN,
    LOGGER,
    PROXMOX_CLIENT,
    ProxmoxCommand,
    ProxmoxType,
)
from .entity import ProxmoxEntity, ProxmoxEntityDescription


@dataclass(frozen=True, kw_only=True)
class ProxmoxButtonEntityDescription(ProxmoxEntityDescription, ButtonEntityDescription):
    """Class describing Proxmox buttons entities."""

    api_category: ProxmoxType | None = (
        None  # Set when the sensor applies to only QEMU or LXC, if None applies to both.
    )


PROXMOX_BUTTON_NODE: Final[tuple[ProxmoxButtonEntityDescription, ...]] = (
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.START_ALL,
        icon="mdi:play",
        name="Start all",
        entity_registry_enabled_default=False,
        translation_key="start_all",
    ),
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.STOP_ALL,
        icon="mdi:stop",
        name="Stop all",
        entity_registry_enabled_default=False,
        translation_key="stop_all",
    ),
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.SHUTDOWN,
        icon="mdi:server-off",
        name="Shutdown",
        entity_registry_enabled_default=False,
        translation_key="shutdown",
    ),
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.REBOOT,
        icon="mdi:restart",
        name="Reboot",
        entity_registry_enabled_default=False,
        translation_key="reboot",
    ),
)

PROXMOX_BUTTON_VM: Final[tuple[ProxmoxButtonEntityDescription, ...]] = (
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.REBOOT,
        icon="mdi:restart",
        name="Reboot",
        entity_registry_enabled_default=False,
        translation_key="reboot",
    ),
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.START,
        icon="mdi:server",
        name="Start",
        entity_registry_enabled_default=False,
        translation_key="start",
    ),
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.SHUTDOWN,
        icon="mdi:server-off",
        name="Shutdown",
        entity_registry_enabled_default=False,
        translation_key="shutdown",
    ),
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.STOP,
        icon="mdi:stop",
        name="Stop",
        entity_registry_enabled_default=False,
        translation_key="stop",
    ),
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.RESUME,
        icon="mdi:play",
        name="Resume",
        api_category=ProxmoxType.QEMU,
        entity_registry_enabled_default=False,
        translation_key="resume",
    ),
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.SUSPEND,
        icon="mdi:pause",
        name="Suspend",
        api_category=ProxmoxType.QEMU,
        entity_registry_enabled_default=False,
        translation_key="suspend",
    ),
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.HIBERNATE,
        icon="mdi:bed",
        name="Hibernate",
        api_category=ProxmoxType.QEMU,
        entity_registry_enabled_default=False,
        translation_key="hibernate",
    ),
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.RESET,
        icon="mdi:restart-alert",
        name="Reset",
        api_category=ProxmoxType.QEMU,
        entity_registry_enabled_default=False,
        translation_key="reset",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up button."""

    buttons = []

    coordinators = hass.data[DOMAIN][config_entry.entry_id][COORDINATORS]
    proxmox_client = hass.data[DOMAIN][config_entry.entry_id][PROXMOX_CLIENT]

    for node in config_entry.data[CONF_NODES]:
        if f"{ProxmoxType.Node}_{node}" in coordinators:
            coordinator = coordinators[f"{ProxmoxType.Node}_{node}"]
        else:
            continue

        # unfound vm case
        if coordinator.data is not None:
            for description in PROXMOX_BUTTON_NODE:
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

    for vm_id in config_entry.data[CONF_QEMU]:
        if f"{ProxmoxType.QEMU}_{vm_id}" in coordinators:
            coordinator = coordinators[f"{ProxmoxType.QEMU}_{vm_id}"]
        else:
            continue

        # unfound vm case
        if coordinator.data is None:
            continue
        for description in PROXMOX_BUTTON_VM:
            if (
                (api_category := description.api_category)
                and ProxmoxType.QEMU in api_category
                or api_category is None
            ):
                buttons.append(
                    create_button(
                        coordinator=coordinator,
                        info_device=device_info(
                            hass=hass,
                            config_entry=config_entry,
                            api_category=ProxmoxType.QEMU,
                            resource_id=vm_id,
                        ),
                        description=description,
                        resource_id=vm_id,
                        proxmox_client=proxmox_client,
                        api_category=ProxmoxType.QEMU,
                        config_entry=config_entry,
                    )
                )

    for ct_id in config_entry.data[CONF_LXC]:
        if f"{ProxmoxType.LXC}_{ct_id}" in coordinators:
            coordinator = coordinators[f"{ProxmoxType.LXC}_{ct_id}"]
        else:
            continue
        # unfound container case
        if coordinator.data is None:
            continue
        for description in PROXMOX_BUTTON_VM:
            if (
                (api_category := description.api_category)
                and ProxmoxType.LXC in api_category
                or api_category is None
            ):
                buttons.append(
                    create_button(
                        coordinator=coordinator,
                        info_device=device_info(
                            hass=hass,
                            config_entry=config_entry,
                            api_category=ProxmoxType.LXC,
                            resource_id=ct_id,
                        ),
                        description=description,
                        resource_id=ct_id,
                        proxmox_client=proxmox_client,
                        api_category=ProxmoxType.LXC,
                        config_entry=config_entry,
                    )
                )

    async_add_entities(buttons)


def create_button(
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

        def _button_press():
            """Post start command & tell HA state is on."""

            if api_category == ProxmoxType.Node:
                node = resource_id
                vm_id = None
            else:
                if (data := self.coordinator.data) is None:
                    return None
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
