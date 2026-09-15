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
from packaging.version import InvalidVersion, Version

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
        name="Software update",
        icon="mdi:package-up",
        entity_category=EntityCategory.CONFIG,
        translation_key="node_update",
    )
)


@dataclass(frozen=True)
class ProxmoxUpdateInfo:
    """What the update entity says about a node's pending upgrade."""

    latest_version: str
    latest_version_id: str
    total_updates: int
    proxmox_updates: int
    other_updates: int


def _comparable(version: str) -> Version:
    """
    Turn a Debian version into something `packaging` can order.

    Proxmox versions carry `-pve1`-style suffixes, which are dropped like
    the core integration does. Anything `packaging` still cannot read - an
    epoch such as `2:1.0`, say - sorts lowest instead of raising.
    """
    try:
        return Version(version.split("-", maxsplit=1)[0])
    except InvalidVersion:
        return Version("0")


def latest_version(versions: list[str]) -> str:
    """Return the highest of the given versions, suffixes ignored."""
    return max((version.split("-")[0] for version in versions), key=_comparable)


def update_version(installed: str, packages: list[dict]) -> ProxmoxUpdateInfo:
    """
    Describe a pending upgrade the way the core integration does.

    The latest version is the highest version among the installed release
    and Proxmox's own pending packages; the id Home Assistant compares
    against the installed version carries the pending counts as well, so
    it changes whenever the set of pending packages does, not only when a
    Proxmox package is among them.
    """
    total = len(packages)
    proxmox = [entry for entry in packages if entry["proxmox"]]
    other = total - len(proxmox)
    latest = (
        latest_version([installed, *(str(entry["version"]) for entry in proxmox)])
        if proxmox
        else installed
    )
    return ProxmoxUpdateInfo(
        latest_version=latest if total else installed,
        latest_version_id=f"{latest}-p{len(proxmox)}-d{other}" if total else installed,
        total_updates=total,
        proxmox_updates=len(proxmox),
        other_updates=other,
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

    def _update_info(self) -> ProxmoxUpdateInfo | None:
        """Return the pending upgrade, or None when it could not be read."""
        data: ProxmoxUpdateData | None = self.coordinator.data
        if data is None or data.total is UNDEFINED:
            return None
        return update_version(self.installed_version or "unknown", data.packages)

    @property
    def available(self) -> bool:
        """Return whether the pending updates could be read."""
        return super().available and self._update_info() is not None

    @property
    def installed_version(self) -> str | None:
        """Return the Proxmox VE version the node runs."""
        if (node_data := self._node_coordinator.data) is None:
            return "unknown"
        version = node_data.version
        return "unknown" if version is UNDEFINED else str(version)

    @property
    def latest_version(self) -> str | None:
        """Return the version id Home Assistant compares with the installed one."""
        info = self._update_info()
        return info.latest_version_id if info else None

    @property
    def release_summary(self) -> str | None:
        """Return the core integration's account of what is pending."""
        info = self._update_info()
        if info is None or not info.total_updates:
            return None
        url = self.device_info.get("configuration_url") if self.device_info else None
        return (
            f"A total of {info.total_updates} package update(s) are pending "
            f"installation: of these {info.proxmox_updates} relate to Proxmox and "
            f"{info.other_updates} to other updates. Please visit the "
            f"[Proxmox VE node]({url}) for details on the pending updates and to "
            f"upgrade to {info.latest_version}."
        )

    def release_notes(self) -> str | None:
        """Return the release notes for the update."""
        return self.release_summary
