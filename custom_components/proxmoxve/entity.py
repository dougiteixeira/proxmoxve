# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""
Proxmox parent entity class, and the optional entity id scheme.

Home Assistant builds an entity id from the device name and the entity
name - `sensor.qemu_docmost_109_cpu_used`, `sensor.node_pve_cpu_used` -
which puts the kind first and the id last, and nothing in front that
would let a recorder filter or a search catch everything of this
integration. That is the **standard** scheme. The **extended** scheme
puts a common prefix first and the id before the name:

    <prefix>_cluster_<item>
    <prefix>_node_<node>_<item>
    <prefix>_qemu_<vmid>_<name>_<item>      <prefix>_lxc_<vmid>_<name>_<item>
    <prefix>_storage_<node>_<storage>_<item> <prefix>_storage_<storage>_<item>
    <prefix>_disk_<node>_<model>_<item>      <prefix>_zfs_<node>_<pool>_<item>

`<item>` is the entity's translation key (or its English name), so the
ids read the same in every language. The scheme is a suggestion Home Assistant takes when it
registers an entity for the first time: entities that already have an id
keep it, whatever the option says.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.util import slugify

from .const import (
    CONF_ENTITY_ID_PREFIX,
    CONF_ENTITY_ID_SCHEME,
    DEFAULT_ENTITY_ID_PREFIX,
    SCHEME_EXTENDED,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import EntityPlatform


@dataclasses.dataclass(frozen=True, kw_only=True)
class ProxmoxEntityDescription(EntityDescription):
    """Describe a Proxmox entity."""


def scheme_object_id(
    prefix: str,
    identifier: str,
    device_name: str | None,
    item: str,
    guest_name: str | None = None,
) -> str:
    """
    Build the object id of the extended scheme from the device identifier.

    `identifier` is the device identifier without the entry id in front:
    `cluster`, `NODE_pve`, `QEMU_108`, `STORAGE_pve/local`, `STORAGE_nas`,
    `DISK_pve_<id>`, `ZFS_pve_<pool>`. The guest's name comes from its data
    when given, otherwise from the device name `QEMU <name> (<vmid>)`; a
    disk is named by its model, the tail of `Disk <node>: <model>`.
    """
    kind, _, rest = identifier.partition("_")
    kind = kind.lower()
    parts: list[str]
    if kind == "cluster":
        parts = ["cluster"]
    elif kind in ("qemu", "lxc"):
        name = guest_name
        if name is None and device_name:
            name = device_name
            for cut in (f"{kind.upper()} ", f" ({rest})"):
                name = name.removeprefix(cut).removesuffix(cut)
        parts = [kind, rest, name or ""]
    elif kind == "storage":
        parts = ["storage", *rest.split("/")]
    elif kind in ("disk", "zfs"):
        node, _, resource = rest.partition("_")
        if kind == "disk" and device_name and ": " in device_name:
            resource = device_name.split(": ", 1)[1]
        parts = [kind, node, resource]
    else:
        parts = [kind, rest]
    return slugify(" ".join(part for part in [prefix, *parts, item] if part))


class ProxmoxEntity(CoordinatorEntity):
    """Represents any entity created for the Proxmox VE platform."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        unique_id: str,
        description: ProxmoxEntityDescription,
    ) -> None:
        """Initialize the Proxmox entity."""
        super().__init__(coordinator)

        self.coordinator = coordinator
        self.entity_description = description
        self._attr_unique_id = unique_id

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success

    def add_to_platform_start(
        self,
        hass: HomeAssistant,
        platform: EntityPlatform,
        parallel_updates: Any,
    ) -> None:
        """
        Suggest the entity id of the extended scheme, when the option asks for it.

        This runs before Home Assistant picks an entity id. An entity the
        registry already knows keeps its id regardless; the suggestion only
        counts for entities registered for the first time.
        """
        super().add_to_platform_start(hass, platform, parallel_updates)
        if (
            self.entity_id is not None
            or (object_id := self._scheme_object_id()) is None
        ):
            return
        self.entity_id = f"{platform.domain}.{object_id}"

    def _scheme_object_id(self) -> str | None:
        config_entry = getattr(self.coordinator, "config_entry", None)
        if (
            config_entry is None
            or config_entry.options.get(CONF_ENTITY_ID_SCHEME) != SCHEME_EXTENDED
        ):
            return None
        info = self.device_info or {}
        identifier = next(
            (
                ident[len(config_entry.entry_id) + 1 :]
                for _, ident in info.get("identifiers", ())
                if ident.startswith(f"{config_entry.entry_id}_")
            ),
            None,
        )
        if identifier is None:
            return None
        prefix = (
            config_entry.options.get(CONF_ENTITY_ID_PREFIX) or DEFAULT_ENTITY_ID_PREFIX
        )
        description = self.entity_description
        # The translation key where there is one, else the English name a
        # description carries, else the key - what the item reads as.
        item = (
            getattr(description, "translation_key", None)
            or (description.name if isinstance(description.name, str) else None)
            or description.key
        )
        return scheme_object_id(
            prefix,
            identifier,
            info.get("name"),
            item,
            getattr(self.coordinator.data, "name", None),
        )
