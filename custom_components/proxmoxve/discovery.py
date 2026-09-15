# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""
Keep the tracked nodes, guests and storages in step with the cluster.

By default this integration tracks exactly what was picked in the options.
With automatic discovery on, `cluster/resources` is the truth instead:
whatever the cluster lists is tracked, and whatever it no longer lists is
dropped, devices included.

The selection in the config entry is never touched by this. What is tracked
lives in the entry's runtime data, so switching discovery off again brings
the old selection back at the next reload, exactly as it was.

At setup the tracked set is taken from the cluster before the coordinators
are built from it. Afterwards a coordinator keeps comparing, and - like the
Home Assistant core integration - adds the coordinators, device and
entities of a new resource on the spot and removes those of a vanished one,
without reloading anything.
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
    TRACKED,
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


def selected(config_entry: ConfigEntry, key: str, only: list[str] | None) -> list[str]:
    """
    Return the resources a platform should build entities for.

    At setup that is everything this setup tracks under `key` - the picked
    selection, or the cluster's list with discovery on; when discovery adds
    a resource at runtime, only that one.
    """
    return only if only is not None else tracked_resources(config_entry)[key]


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


def selected_resources(config_entry: ConfigEntry) -> dict[str, list[str]]:
    """Return what was picked in the config entry, as strings like the discovery."""
    return {
        key: [str(value) for value in config_entry.data.get(key, [])]
        for key in RESOURCE_KEYS.values()
    }


def tracked_resources(config_entry: ConfigEntry) -> dict[str, list[str]]:
    """
    Return what this setup tracks.

    That is the runtime set once setup has decided it - the selection, or
    the cluster's list with discovery on - and the selection before that.
    """
    runtime = getattr(config_entry, "runtime_data", None)
    if isinstance(runtime, dict) and TRACKED in runtime:
        return {key: list(values) for key, values in runtime[TRACKED].items()}
    return selected_resources(config_entry)


def resource_changes(
    config_entry: ConfigEntry,
    found: dict[str, list[str]],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Return what `found` adds to and removes from what the entry tracks."""
    tracked = tracked_resources(config_entry)
    added = {
        key: sorted(set(found[key]) - set(tracked[key]), key=_sort_key)
        for key in RESOURCE_KEYS.values()
    }
    removed = {
        key: sorted(set(tracked[key]) - set(found[key]), key=_sort_key)
        for key in RESOURCE_KEYS.values()
    }
    return added, removed


def _sort_key(value: str) -> tuple[int, str]:
    """Order guest ids numerically and everything else by name."""
    return (int(value), "") if value.isdigit() else (0, value)


def remember_resources(
    config_entry: ConfigEntry,
    found: dict[str, list[str]],
) -> None:
    """Make the runtime track exactly `found`, and log the difference."""
    added, removed = resource_changes(config_entry, found)
    for key in RESOURCE_KEYS.values():
        if added[key] or removed[key]:
            LOGGER.info(
                "Discovery: %s added %s, removed %s",
                key,
                added[key] or "nothing",
                removed[key] or "nothing",
            )
    tracked = config_entry.runtime_data[TRACKED]
    tracked.clear()
    tracked.update({key: list(values) for key, values in found.items()})


def remove_stale_devices(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    found: dict[str, list[str]],
) -> None:
    """
    Detach every device of a node, guest or storage the cluster does not list.

    Run at setup with discovery on, so devices left over from an earlier
    session - a guest deleted while Home Assistant was down, or one picked
    by hand that no longer exists - do not linger. The cluster device and
    anything else this cannot place are left alone.
    """
    nodes = set(found[CONF_NODES])
    present = {
        ProxmoxType.QEMU.upper(): set(found[CONF_QEMU]),
        ProxmoxType.LXC.upper(): set(found[CONF_LXC]),
        ProxmoxType.Storage.upper(): {
            storage.replace("storage/", "") for storage in found[CONF_STORAGE]
        },
        ProxmoxType.Node.upper(): nodes,
    }
    prefix = f"{config_entry.entry_id}_"

    def _stale(identifier: str) -> bool:
        if not identifier.startswith(prefix):
            return False
        kind, _, rest = identifier.removeprefix(prefix).partition("_")
        if kind in (ProxmoxType.Disk.upper(), ProxmoxType.ZFS.upper()):
            # `<DISK|ZFS>_<node>_<id>`; node names carry no underscore.
            return rest.partition("_")[0] not in nodes
        return kind in present and rest not in present[kind]

    dev_reg = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(dev_reg, config_entry.entry_id):
        identifiers = [
            identifier for domain, identifier in device.identifiers if domain == DOMAIN
        ]
        if any(_stale(identifier) for identifier in identifiers):
            LOGGER.debug("Discovery: removing stale device %s", identifiers)
            dev_reg.async_update_device(
                device_id=device.id,
                remove_config_entry_id=config_entry.entry_id,
            )


def remove_resource_devices(
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
