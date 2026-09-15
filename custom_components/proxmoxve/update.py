# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Update entity for pending package upgrades on a Proxmox VE node."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from homeassistant.components.update import (
    UpdateEntity,
    UpdateEntityDescription,
    UpdateEntityFeature,
)
from homeassistant.const import EntityCategory
from homeassistant.helpers.typing import UNDEFINED

from . import device_info
from .const import CONF_NODES, COORDINATORS, ProxmoxType
from .entity import ProxmoxEntity, ProxmoxEntityDescription

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.device_registry import DeviceInfo
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import ProxmoxNodeCoordinator, ProxmoxUpdateCoordinator
    from .models import ProxmoxUpdateData


@dataclass(frozen=True, kw_only=True)
class ProxmoxUpdateEntityDescription(ProxmoxEntityDescription, UpdateEntityDescription):
    """Class describing Proxmox update entities."""


PROXMOX_UPDATE_NODE: Final[ProxmoxUpdateEntityDescription] = (
    ProxmoxUpdateEntityDescription(
        key="node_update",
        name="Updates",
        icon="mdi:package-up",
        entity_category=EntityCategory.CONFIG,
        translation_key="node_update",
    )
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the per-node update entities."""
    coordinators = config_entry.runtime_data[COORDINATORS]
    entities = []

    for node in config_entry.data[CONF_NODES]:
        coordinator = coordinators.get(f"{ProxmoxType.Update}_{node}")
        node_coordinator = coordinators.get(f"{ProxmoxType.Node}_{node}")
        if coordinator is None or node_coordinator is None:
            continue
        # Reading `apt/update` needs Sys.Modify. Without it the coordinator
        # reports nothing (and raises a repair issue saying which permission
        # is missing), and an update entity that can never know anything is
        # worse than none.
        if coordinator.data is None or coordinator.data.total is UNDEFINED:
            continue

        entities.append(
            ProxmoxUpdateEntity(
                coordinator=coordinator,
                node_coordinator=node_coordinator,
                info_device=device_info(
                    hass=hass,
                    config_entry=config_entry,
                    api_category=ProxmoxType.Node,
                    node=node,
                ),
                description=PROXMOX_UPDATE_NODE,
                unique_id=f"{config_entry.entry_id}_{node}_{PROXMOX_UPDATE_NODE.key}",
            )
        )

    async_add_entities(entities)


class ProxmoxUpdateEntity(ProxmoxEntity, UpdateEntity):
    """
    The pending package upgrade of a Proxmox VE node.

    Backed by the node's update coordinator, which is what changes; the
    installed version comes from the node coordinator, which already reads
    it and refreshes at the same rate.

    Installing is deliberately not offered: `apt/upgrade` has no API
    endpoint, and a dist-upgrade of a hypervisor is not something to start
    from a dashboard button.
    """

    entity_description: ProxmoxUpdateEntityDescription
    _attr_supported_features = UpdateEntityFeature.RELEASE_NOTES
    _attr_title = "Proxmox VE"

    def __init__(
        self,
        *,
        coordinator: ProxmoxUpdateCoordinator,
        node_coordinator: ProxmoxNodeCoordinator,
        info_device: DeviceInfo,
        description: ProxmoxUpdateEntityDescription,
        unique_id: str,
    ) -> None:
        """Create the update entity for a node."""
        super().__init__(coordinator, unique_id, description)

        self._attr_device_info = info_device
        self._node_coordinator = node_coordinator

    @property
    def _updates(self) -> ProxmoxUpdateData | None:
        """Return the update data when the node could be read."""
        data = self.coordinator.data
        if data is None or data.total is UNDEFINED:
            return None
        return data

    @property
    def available(self) -> bool:
        """Return whether the pending updates could be read."""
        return super().available and self._updates is not None

    @property
    def installed_version(self) -> str | None:
        """Return the Proxmox VE version the node runs."""
        if (node_data := self._node_coordinator.data) is None:
            return None
        version = node_data.version
        return None if version is UNDEFINED else str(version)

    @property
    def latest_version(self) -> str | None:
        """
        Return what the node would run after upgrading.

        Home Assistant shows an update whenever this differs from the
        installed version. A pending `pve-manager` names the release; when
        only other packages wait, the release stays the same, so the count
        is appended to make the difference visible - and to move again when
        further packages arrive.
        """
        if (data := self._updates) is None:
            return None
        installed = self.installed_version
        if not data.total:
            return installed
        release = data.proxmox_version_pending or installed or "unknown"
        noun = "update" if data.total == 1 else "updates"
        return f"{release} ({data.total} {noun})"

    @property
    def release_summary(self) -> str | None:
        """Return a one-line account of what is pending."""
        if (data := self._updates) is None or not data.total:
            return None
        noun = "package" if data.total == 1 else "packages"
        return (
            f"{data.total} {noun} pending: {data.proxmox_updates} from Proxmox, "
            f"{data.other_updates} from Debian or other repositories."
        )

    def release_notes(self) -> str | None:
        """Return the pending packages as a Markdown list."""
        if (data := self._updates) is None or not data.packages:
            return None
        lines = [
            f"- `{entry['package']}` {entry['version']}"
            + ("" if entry["proxmox"] else " *(other)*")
            for entry in data.packages
        ]
        return (
            f"{self.release_summary}\n\n"
            + "\n".join(lines)
            + "\n\nUpgrade from the node's shell (`apt dist-upgrade`) or its web "
            "interface; the API offers no way to do it from here."
        )
