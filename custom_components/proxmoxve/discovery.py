# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""
Keep the tracked nodes, guests and storages in step with the cluster.

By default this integration tracks exactly what was picked in the options.
With automatic discovery on, the picked set becomes the starting point and
`cluster/resources` the truth: whatever the cluster lists is tracked, and
whatever it no longer lists is dropped, devices included.

The integration builds one coordinator per resource at setup, so a change
here is followed by a reload of the config entry rather than by creating
entities on the fly. A new guest is a rare event, and a reload takes a few
seconds; that is a far smaller price than teaching every platform to add
and remove entities at runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.helpers import device_registry as dr

from .const import (
    CONF_LXC,
    CONF_NODES,
    CONF_QEMU,
    CONF_STORAGE,
    DOMAIN,
    LOGGER,
    ProxmoxType,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

# The four lists in the config entry and how each resource type maps to them.
RESOURCE_KEYS: dict[str, str] = {
    ProxmoxType.Node: CONF_NODES,
    ProxmoxType.QEMU: CONF_QEMU,
    ProxmoxType.LXC: CONF_LXC,
    ProxmoxType.Storage: CONF_STORAGE,
}


def discovered_resources(resources: list[dict[str, Any]]) -> dict[str, list[str]]:
    """
    Return the nodes, guests and storages a `cluster/resources` listing carries.

    Templates are left out: a template never runs, so every sensor on it
    would say "stopped" forever and every button would fail.
    """
    found: dict[str, set[str]] = {key: set() for key in RESOURCE_KEYS.values()}
    for resource in resources:
        if not isinstance(resource, dict) or resource.get("template"):
            continue
        match resource.get("type"):
            case ProxmoxType.Node if "node" in resource:
                found[CONF_NODES].add(str(resource["node"]))
            case ProxmoxType.QEMU if "vmid" in resource:
                found[CONF_QEMU].add(str(resource["vmid"]))
            case ProxmoxType.LXC if "vmid" in resource:
                found[CONF_LXC].add(str(resource["vmid"]))
            case ProxmoxType.Storage if "id" in resource:
                found[CONF_STORAGE].add(str(resource["id"]))

    return {
        CONF_NODES: sorted(found[CONF_NODES]),
        CONF_QEMU: sorted(found[CONF_QEMU], key=int),
        CONF_LXC: sorted(found[CONF_LXC], key=int),
        CONF_STORAGE: sorted(found[CONF_STORAGE]),
    }


def tracked_resources(config_entry: ConfigEntry) -> dict[str, list[str]]:
    """Return what the config entry tracks, as strings like the discovery."""
    return {
        key: [str(value) for value in config_entry.data.get(key, [])]
        for key in RESOURCE_KEYS.values()
    }


def apply_discovery(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    found: dict[str, list[str]],
) -> bool:
    """
    Make the config entry track exactly what the cluster lists.

    Returns whether anything changed. Devices of resources the cluster no
    longer has are detached from the entry, which removes them; the
    coordinators for anything new are created by the setup that follows.
    """
    tracked = tracked_resources(config_entry)
    if all(set(tracked[key]) == set(found[key]) for key in RESOURCE_KEYS.values()):
        return False

    for key in RESOURCE_KEYS.values():
        added = sorted(set(found[key]) - set(tracked[key]))
        removed = sorted(set(tracked[key]) - set(found[key]))
        if added or removed:
            LOGGER.info(
                "Discovery: %s added %s, removed %s",
                key,
                added or "nothing",
                removed or "nothing",
            )

    _remove_devices(
        hass,
        config_entry,
        {
            key: sorted(set(tracked[key]) - set(found[key]))
            for key in RESOURCE_KEYS.values()
        },
    )

    hass.config_entries.async_update_entry(
        config_entry,
        data={**config_entry.data, **found},
    )
    return True


def _remove_devices(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    removed: dict[str, list[str]],
) -> None:
    """
    Detach the devices of resources that are gone from the cluster.

    Device identifiers are `<entry>_<TYPE>_<id>`; a node also owns the disk
    and ZFS pool devices under it, whose identifiers start with the node's
    name. Those are found by prefix rather than through coordinators so this
    works during setup as well, before any coordinator exists.
    """
    exact: set[str] = set()
    prefixes: list[str] = []
    for api_category, key in RESOURCE_KEYS.items():
        for resource_id in removed[key]:
            resource_key = (
                resource_id.replace("storage/", "")
                if api_category is ProxmoxType.Storage
                else resource_id
            )
            exact.add(f"{config_entry.entry_id}_{api_category.upper()}_{resource_key}")
            if api_category is ProxmoxType.Node:
                prefixes.extend(
                    f"{config_entry.entry_id}_{owned.upper()}_{resource_id}_"
                    for owned in (ProxmoxType.Disk, ProxmoxType.ZFS)
                )
    if not exact:
        return

    dev_reg = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(dev_reg, config_entry.entry_id):
        identifiers = [
            identifier for domain, identifier in device.identifiers if domain == DOMAIN
        ]
        if any(
            identifier in exact
            or any(identifier.startswith(prefix) for prefix in prefixes)
            for identifier in identifiers
        ):
            LOGGER.debug("Discovery: removing device %s", identifiers)
            dev_reg.async_update_device(
                device_id=device.id,
                remove_config_entry_id=config_entry.entry_id,
            )
