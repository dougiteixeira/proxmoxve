"""Button to set Proxmox VE data."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from . import ProxmoxClient, ProxmoxEntity, call_api_post_status, device_info
from .const import (
    CONF_LXC,
    CONF_NODE,
    CONF_QEMU,
    COORDINATORS,
    DOMAIN,
    LOGGER,
    PROXMOX_CLIENT,
    ProxmoxCommand,
    ProxmoxType,
)


@dataclass
class ProxmoxButtonEntityDescription(ButtonEntityDescription):
    """Class describing Proxmox buttons entities."""

    api_category: ProxmoxType | None = None  # Set when the sensor applies to only QEMU or LXC, if None applies to both.


PROXMOX_BUTTON_NODE: Final[tuple[ProxmoxButtonEntityDescription, ...]] = (
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.START_ALL,
        icon="mdi:play",
        name="Start All",
        entity_registry_enabled_default=False,
    ),
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.STOP_ALL,
        icon="mdi:stop",
        name="Stop All",
        entity_registry_enabled_default=False,
    ),
)

PROXMOX_BUTTON_VM: Final[tuple[ProxmoxButtonEntityDescription, ...]] = (
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.REBOOT,
        icon="mdi:restart",
        name="Reboot",
        entity_registry_enabled_default=False,
    ),
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.START,
        icon="mdi:server",
        name="Start",
        entity_registry_enabled_default=False,
    ),
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.SHUTDOWN,
        icon="mdi:server-off",
        name="Shutdown",
        entity_registry_enabled_default=False,
    ),
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.STOP,
        icon="mdi:stop",
        name="Stop",
        entity_registry_enabled_default=False,
    ),
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.RESUME,
        icon="mdi:play",
        name="Resume",
        entity_registry_enabled_default=False,
    ),
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.SUSPEND,
        icon="mdi:pause",
        name="Suspend",
        entity_registry_enabled_default=False,
    ),
    ProxmoxButtonEntityDescription(
        key=ProxmoxCommand.RESET,
        icon="mdi:restart-alert",
        name="Reset",
        entity_registry_enabled_default=False,
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

    coordinator = coordinators[ProxmoxType.Node]
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
                        vm_id=None,
                    ),
                    description=description,
                    vm_id=None,
                    proxmox_client=proxmox_client,
                    api_category=ProxmoxType.Node,
                    config_entry=config_entry,
                )
            )

    for vm_id in config_entry.data[CONF_QEMU]:
        coordinator = coordinators[vm_id]
        # unfound vm case
        if coordinator.data is None:
            continue
        for description in PROXMOX_BUTTON_VM:
            if description.api_category in (None, ProxmoxType.QEMU):
                buttons.append(
                    create_button(
                        coordinator=coordinator,
                        info_device=device_info(
                            hass=hass,
                            config_entry=config_entry,
                            api_category=ProxmoxType.QEMU,
                            vm_id=vm_id,
                        ),
                        description=description,
                        vm_id=vm_id,
                        proxmox_client=proxmox_client,
                        api_category=ProxmoxType.QEMU,
                        config_entry=config_entry,
                    )
                )

    for ct_id in config_entry.data[CONF_LXC]:
        coordinator = coordinators[ct_id]
        # unfound container case
        if coordinator.data is None:
            continue
        for description in PROXMOX_BUTTON_VM:
            if description.api_category in (None, ProxmoxType.LXC):
                buttons.append(
                    create_button(
                        coordinator=coordinator,
                        info_device=device_info(
                            hass=hass,
                            config_entry=config_entry,
                            api_category=ProxmoxType.LXC,
                            vm_id=ct_id,
                        ),
                        description=description,
                        vm_id=ct_id,
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
    config_entry: ConfigEntry,
    vm_id: str | None = None,
):
    """Create a button based on the given data."""
    return ProxmoxButtonEntity(
        description=description,
        proxmox_client=proxmox_client,
        api_category=api_category,
        coordinator=coordinator,
        unique_id=f"{config_entry.entry_id}_{vm_id}_{description.key}",
        vm_id=vm_id,
        info_device=info_device,
        config_entry=config_entry,
    )


class ProxmoxButtonEntity(ProxmoxEntity, ButtonEntity):
    """A button for reading/writing Proxmox VE status."""

    entity_description: ProxmoxButtonEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        info_device: DeviceInfo,
        description: ProxmoxButtonEntityDescription,
        unique_id: str,
        proxmox_client: ProxmoxClient,
        api_category: ProxmoxType,
        config_entry,
        vm_id: str | None = None,
    ) -> None:
        """Create the button for vms or containers."""
        super().__init__(coordinator, unique_id, description.name, description.icon)

        self._attr_device_info = info_device
        self.entity_description = description

        def _button_press():
            """Post start command & tell HA state is on."""
            call_api_post_status(
                proxmox=proxmox_client.get_api_client(),
                node=config_entry.data[CONF_NODE],
                vm_id=vm_id,
                api_category=api_category,
                command=description.key,
            )

            LOGGER.debug(
                "Button press: %s - %s - %s - %s",
                config_entry.data[CONF_NODE],
                vm_id,
                api_category,
                description.key,
            )

        self._button_press_funct = _button_press

    @property
    def available(self) -> bool:
        """Return sensor availability."""
        return super().available and self.coordinator.data is not None

    def press(self) -> None:
        """Press the button."""
        self._button_press_funct()
