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
from homeassistant.const import CONF_HOST, CONF_PORT, EntityCategory
from homeassistant.helpers.typing import UNDEFINED
from packaging.version import InvalidVersion, Version

from . import device_info
from .const import CONF_NODES, COORDINATORS, RESOURCE_CALLBACKS, ProxmoxType
from .discovery import selected
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


# The package that carries the Proxmox VE release. `pveversion` reports
# what `pve-manager` is at, so that is the one package whose pending
# version is the node's pending release. Everything else Proxmox ships
# has its own numbering - the bundled Ceph libraries are at 19.x - and
# comparing those with the release number claims the node is about to
# become Proxmox VE 19.
RELEASE_PACKAGE = "pve-manager"


def latest_version(versions: list[str]) -> str:
    """Return the highest of the given versions, suffixes ignored."""
    return max((version.split("-")[0] for version in versions), key=_comparable)


def update_version(installed: str, packages: list[dict]) -> ProxmoxUpdateInfo:
    """
    Describe a pending upgrade: which release, and how much is waiting.

    The latest version is what the pending `pve-manager` would install,
    since that is the package `pveversion` reports - not the highest
    version among Proxmox's pending packages, which on a node with the
    bundled Ceph libraries waiting is Ceph's 19.x and has nothing to do
    with the Proxmox VE release. With no `pve-manager` pending the release
    stays where it is.

    The id Home Assistant compares against the installed version carries
    the pending counts as well, so it changes whenever the set of pending
    packages does, not only when the release moves.
    """
    total = len(packages)
    proxmox = [entry for entry in packages if entry["proxmox"]]
    other = total - len(proxmox)
    release = next(
        (
            str(entry["version"])
            for entry in packages
            if entry["package"] == RELEASE_PACKAGE
        ),
        None,
    )
    latest = latest_version([installed, release]) if release else installed
    return ProxmoxUpdateInfo(
        latest_version=latest if total else installed,
        latest_version_id=f"{latest}-p{len(proxmox)}-d{other}" if total else installed,
        total_updates=total,
        proxmox_updates=len(proxmox),
        other_updates=other,
    )


# What a release note has to survive being read as markdown: a Debian
# version carries a tilde - `1:9.20.26-1~deb13u1` - and a single tilde
# opens a strikethrough, so the two versions of one line struck each
# other out in the dialog. A package title is free text from apt and can
# hold any of these characters as well.
_MARKDOWN_SPECIALS = str.maketrans(
    {character: f"\\{character}" for character in "\\`*_[]~"}
)


def _as_text(value: str) -> str:
    """Return `value` so markdown shows it as it is."""
    return value.translate(_MARKDOWN_SPECIALS)


def _package_line(entry: dict[str, str | bool]) -> str:
    """
    Return one pending package as a list item: what it is, and what changes.

    The versions go in code spans - a tilde is literal in there, and a
    version reads as the machine word it is.

    A package apt would install rather than upgrade has no version to
    come from - a new kernel brings its own versioned package names with
    it - and is said to be new, rather than shown as a single version
    that reads like the rest of the line went missing.
    """
    title = _as_text(str(entry["title"]))
    package = str(entry["package"])
    version = str(entry["version"])
    old = str(entry.get("old", ""))
    change = f"`{old}` \u2192 `{version}`" if old else f"new: `{version}`"
    return f"- {title} (`{package}`) \u2014 {change}"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the per-node update entities."""
    async_add_entities(await async_setup_updates(hass, config_entry))

    async def _async_add_resource(api_category: ProxmoxType, resource_id: str) -> None:
        """Build the update entity of a node discovery found at runtime."""
        if api_category is ProxmoxType.Node:
            async_add_entities(
                await async_setup_updates(hass, config_entry, [resource_id])
            )

    config_entry.runtime_data[RESOURCE_CALLBACKS].append(_async_add_resource)


async def async_setup_updates(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    only: list[str] | None = None,
) -> list:
    """Build the update entities of the given nodes, or of all tracked ones."""
    coordinators = config_entry.runtime_data[COORDINATORS]
    entities = []

    for node in selected(config_entry, CONF_NODES, only):
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

    return entities


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
    def release_url(self) -> str | None:
        """
        Return the address of the node's update panel in the web interface.

        What Home Assistant shows as *Read release announcement*. The web
        interface addresses its panels through the fragment: the node, then
        the position of **Updates** in its menu - the same shape as the disk
        and ZFS links on the devices, confirmed against Proxmox VE 9. An
        index the installation does not know lands on the node itself.
        """
        data: ProxmoxUpdateData | None = self.coordinator.data
        if data is None or not (node := data.node):
            return None
        entry_data = self.coordinator.config_entry.data
        host = entry_data[CONF_HOST]
        port = entry_data[CONF_PORT]
        return f"https://{host}:{port}/#v1:0:=node%2F{node}:4:31::::::"

    @property
    def release_summary(self) -> str | None:
        """
        Return one line on what is pending.

        Home Assistant cuts this at 255 characters, so the node's address
        is not in here - it is the release URL - and the packages are in
        the release notes.
        """
        info = self._update_info()
        if info is None or not info.total_updates:
            return None
        summary = (
            f"{info.total_updates} package update(s) pending: "
            f"{info.proxmox_updates} from Proxmox, "
            f"{info.other_updates} from other sources."
        )
        if info.proxmox_updates:
            summary += f" The newest pending Proxmox version is {info.latest_version}."
        return summary

    def release_notes(self) -> str | None:
        """
        Return the pending packages, Proxmox's own first.

        Which package moves from which version to which is what the node's
        own update panel shows, and the reason to look at the entity at all;
        the counts alone say little.
        """
        data: ProxmoxUpdateData | None = self.coordinator.data
        summary = self.release_summary
        if summary is None or data is None:
            return None

        notes = [summary]
        for heading, proxmox in (("Proxmox", True), ("Other", False)):
            lines = [
                _package_line(entry)
                for entry in data.packages
                if bool(entry["proxmox"]) is proxmox
            ]
            if lines:
                notes.append(f"**{heading}**\n\n" + "\n".join(lines))
        return "\n\n".join(notes)
