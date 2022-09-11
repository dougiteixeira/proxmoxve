"""Button to set Proxmox VE data."""
from __future__ import annotations
from dataclasses import dataclass

from typing import Final
from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from . import ProxmoxClient, ProxmoxEntity, call_api_post_status, device_info
from .const import (
    COMMAND_REBOOT,
    COMMAND_RESET,
    COMMAND_RESUME,
    COMMAND_SHUTDOWN,
    COMMAND_START,
    COMMAND_STOP,
    COMMAND_SUSPEND,
    CONF_LXC,
    CONF_NODE,
    CONF_QEMU,
    COORDINATORS,
    DOMAIN,
    PROXMOX_CLIENT,
    ProxmoxType,
    LOGGER,
)


@dataclass
class ProxmoxButtonDescription(ButtonEntityDescription):
    """Class describing Proxmox switch entities."""

    unit_metric: str | None = None
    unit_imperial: str | None = None
    button_command: str | None = None


PROXMOX_BUTTON_TYPES: Final[tuple[ProxmoxButtonDescription, ...]] = (
    ProxmoxButtonDescription(
        key=COMMAND_REBOOT,
        icon="mdi:restart",
        name="Reboot",
    ),
    ProxmoxButtonDescription(
        key=COMMAND_START,
        icon="mdi:server",
        name="Start",
    ),
    ProxmoxButtonDescription(
        key=COMMAND_SHUTDOWN,
        icon="mdi:server-off",
        name="Shutdown",
    ),
    ProxmoxButtonDescription(
        key=COMMAND_STOP,
        icon="mdi:stop",
        name="Stop",
    ),
    ProxmoxButtonDescription(
        key=COMMAND_RESUME,
        icon="mdi:play",
        name="Resume",
        entity_registry_enabled_default=False,
    ),
    ProxmoxButtonDescription(
        key=COMMAND_SUSPEND,
        icon="mdi:pause",
        name="Suspend",
        entity_registry_enabled_default=False,
    ),
    ProxmoxButtonDescription(
        key=COMMAND_RESET,
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

    for vm_id in config_entry.data[CONF_QEMU]:
        coordinator = coordinators[vm_id]

        # unfound vm case
        if coordinator.data is None:
            continue

        for description in PROXMOX_BUTTON_TYPES:
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
                    machine_type=ProxmoxType.QEMU,
                    config_entry=config_entry,
                )
            )

    for ct_id in config_entry.data[CONF_LXC]:
        coordinator = coordinators[ct_id]

        # unfound container case
        if coordinator.data is None:
            continue

        for description in PROXMOX_BUTTON_TYPES:
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
                    machine_type=ProxmoxType.LXC,
                    config_entry=config_entry,
                )
            )

    async_add_entities(buttons)


def create_button(
    coordinator: DataUpdateCoordinator,
    info_device: DeviceInfo,
    description: ProxmoxButtonDescription,
    vm_id: str,
    proxmox_client: ProxmoxClient,
    machine_type: ProxmoxType,
    config_entry,
):
    """Create a button based on the given data."""
    return ProxmoxButton(
        description=description,
        proxmox_client=proxmox_client,
        machine_type=machine_type,
        coordinator=coordinator,
        unique_id=f"proxmox_{config_entry.data[CONF_HOST]}_{config_entry.data[CONF_PORT]}_{config_entry.data[CONF_NODE]}_{vm_id}_{description.key}",
        vm_id=vm_id,
        info_device=info_device,
        config_entry=config_entry,
        name=description.name,
        icon=description.icon,
    )


class ProxmoxButton(ProxmoxEntity, ButtonEntity):
    """A button for reading/writing Proxmox VE status."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        info_device: DeviceInfo,
        description: ProxmoxButtonDescription,
        name: str,
        unique_id: str,
        proxmox_client: ProxmoxClient,
        vm_id: str,
        machine_type: ProxmoxType,
        icon,
        config_entry,
    ) -> None:
        """Create the button for vms or containers."""
        super().__init__(coordinator, unique_id, name, icon, vm_id)

        self._attr_device_info = info_device
        self.entity_description = description

        def _button_press():
            """Post start command & tell HA state is on."""
            call_api_post_status(
                proxmox_client.get_api_client(),
                config_entry.data[CONF_NODE],
                vm_id,
                machine_type,
                description.key,
            )

            LOGGER.debug(
                "Button press: %s - %s - %s - %s",
                config_entry.data[CONF_NODE],
                vm_id,
                machine_type,
                description.key,
            )

        self._button_press_funct = _button_press

    @property
    def available(self):
        """Return sensor availability."""
        return super().available and self.coordinator.data is not None

    def press(self) -> None:
        """Press the button."""
        self._button_press_funct()
