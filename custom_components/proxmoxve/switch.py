"""Switch to set Proxmox VE data."""
from __future__ import annotations

from dataclasses import dataclass

from typing import Any, Final

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator


from . import ProxmoxClient, ProxmoxEntity, call_api_post_status, device_info
from .const import (
    COMMAND_SHUTDOWN,
    COMMAND_START,
    COMMAND_STOP,
    CONF_LXC,
    CONF_NODE,
    CONF_QEMU,
    COORDINATORS,
    DOMAIN,
    PROXMOX_CLIENT,
    LOGGER,
    ProxmoxType,
)


@dataclass
class ProxmoxSwitchDescription(SwitchEntityDescription):
    """Class describing Proxmox switch entities."""

    unit_metric: str | None = None
    unit_imperial: str | None = None
    start_command: str | None = None
    stop_command: str | None = None


PROXMOX_SWITCH_TYPES: Final[tuple[ProxmoxSwitchDescription, ...]] = (
    ProxmoxSwitchDescription(
        key="Switch",
        icon="mdi:server",
        name="Start",
        start_command=COMMAND_START,
        stop_command=COMMAND_SHUTDOWN,
    ),
    ProxmoxSwitchDescription(
        key="Switch_Stop",
        name="Stop",
        icon="mdi:server",
        start_command=COMMAND_START,
        stop_command=COMMAND_STOP,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor."""

    switches = []

    coordinators = hass.data[DOMAIN][config_entry.entry_id][COORDINATORS]
    proxmox_client = hass.data[DOMAIN][config_entry.entry_id][PROXMOX_CLIENT]

    for vm_id in config_entry.data[CONF_QEMU]:
        coordinator = coordinators[vm_id]

        # unfound vm case
        if coordinator.data is None:
            continue

        for description in PROXMOX_SWITCH_TYPES:
            switches.append(
                create_switch(
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

        for description in PROXMOX_SWITCH_TYPES:
            switches.append(
                create_switch(
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

    async_add_entities(switches)


def create_switch(
    coordinator: DataUpdateCoordinator,
    info_device: DeviceInfo,
    description: ProxmoxSwitchDescription,
    vm_id: str,
    proxmox_client: ProxmoxClient,
    machine_type: ProxmoxType,
    config_entry,
):
    """Create a switch based on the given data."""
    return ProxmoxBinarySwitch(
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


class ProxmoxBinarySwitch(ProxmoxEntity, SwitchEntity):
    """A switch for reading/writing Proxmox VE status."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        info_device: DeviceInfo,
        description: ProxmoxSwitchDescription,
        name: str,
        unique_id: str,
        proxmox_client: ProxmoxClient,
        vm_id: str,
        machine_type: ProxmoxType,
        icon,
        config_entry,
    ) -> None:
        """Create the switch for vms or containers."""
        super().__init__(coordinator, unique_id, name, icon, vm_id)

        self._attr_device_info = info_device
        self.entity_description = description
        self.entity_description = description

        def _turn_on_funct():
            """Post start command & tell HA state is on."""
            result = call_api_post_status(
                proxmox_client.get_api_client(),
                config_entry.data[CONF_NODE],
                vm_id,
                machine_type,
                description.start_command,
            )
            if result is not None and COMMAND_START in result:
                # received success acknoledgement from API, set state optimistically to on
                self._attr_is_on = True
                self.async_write_ha_state()
                # TODO - QOL improvement - depending on polling overlap, there is still a possibility for the switch
                # to bounce if the server isn't fully on before the next polling cycle. Ideally need
                # to skip the next polling cycle if there is one scheduled in the next ~10 seconds
            LOGGER.debug(
                "Swtich on: %s - %s - %s - %s",
                config_entry.data[CONF_NODE],
                vm_id,
                machine_type,
                description.start_command,
            )

        def _turn_off_funct():
            """Post shutdown command & tell HA state is off."""
            result = call_api_post_status(
                proxmox_client.get_api_client(),
                config_entry.data[CONF_NODE],
                vm_id,
                machine_type,
                description.stop_command,
            )
            if result is not None and COMMAND_SHUTDOWN in result:
                # received success acknoledgement from API, set state optimistically to off
                self._attr_is_on = False
                self.async_write_ha_state()
                # TODO - QOL improvement - depending on polling overlap, there is still a possibility for the switch
                # to bounce if the server isn't fully off before the next polling cycle. Ideally need
                # to skip the next polling cycle if there is one scheduled in the next ~10 seconds
            LOGGER.debug(
                "Swtich on: %s - %s - %s - %s",
                config_entry.data[CONF_NODE],
                vm_id,
                machine_type,
                description.stop_command,
            )

        self._turn_on_funct = _turn_on_funct
        self._turn_off_funct = _turn_off_funct

    @property
    def is_on(self):
        """Return the switch."""
        if (data := self.coordinator.data) is None:
            return None

        return data["status"] == "running"

    @property
    def available(self):
        """Return sensor availability."""
        return super().available and self.coordinator.data is not None

    def turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        self._turn_on_funct()

    def turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        self._turn_off_funct()
