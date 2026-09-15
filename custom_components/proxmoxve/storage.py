# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""
How a storage is identified, and how a shared one becomes a single thing.

`cluster/resources` lists every storage once per node that has it configured,
as `storage/<node>/<name>` - so an NFS export or a Ceph pool a four-node
cluster mounts everywhere appears four times with the same numbers. Local
storage genuinely differs per node and keeps that id. Shared storage is
tracked as `storage/<name>`, one device on the cluster, with the nodes that
currently see it as an attribute.
"""

from __future__ import annotations

from typing import Any

STORAGE_PREFIX = "storage/"
# `storage/<node>/<name>` has three parts; the shared form `storage/<name>` two.
PER_NODE_ID_PARTS = 3


def storage_name(storage_id: str) -> str:
    """Return the storage's own name from either form of id."""
    return storage_id.rsplit("/", 1)[-1]


def storage_node(storage_id: str) -> str | None:
    """Return the node of a per-node id, or None for a shared one."""
    parts = storage_id.split("/")
    return parts[1] if len(parts) == PER_NODE_ID_PARTS else None


def is_shared_storage_id(storage_id: str) -> bool:
    """Return whether an id is the node-less form used for shared storage."""
    return storage_id.startswith(STORAGE_PREFIX) and storage_id.count("/") == 1


def shared_storage_id(name: str) -> str:
    """Return the id a shared storage is tracked under."""
    return f"{STORAGE_PREFIX}{name}"


def storage_entries(resources: Any) -> list[dict[str, Any]]:
    """Return the storage rows of a `cluster/resources` listing, and nothing else."""
    return [
        resource
        for resource in (resources if isinstance(resources, list) else [])
        if isinstance(resource, dict)
        and resource.get("type") == "storage"
        and isinstance(resource.get("id"), str)
        and resource.get("storage")
    ]


def shared_storage_names(resources: Any) -> set[str]:
    """Return the names of every storage the listing marks as shared."""
    return {
        str(entry["storage"])
        for entry in storage_entries(resources)
        if entry.get("shared") in (1, True, "1")
    }


def tracked_storage_ids(resources: Any) -> list[str]:
    """
    Return the ids to track for a listing: shared storage once, local per node.

    This is the one place the two forms are decided, for discovery, for the
    pick-lists in the config flow and for bringing an older selection up to
    date.
    """
    shared = shared_storage_names(resources)
    ids: set[str] = set()
    for entry in storage_entries(resources):
        name = str(entry["storage"])
        ids.add(shared_storage_id(name) if name in shared else str(entry["id"]))
    return sorted(ids)


def storage_choices(resources: Any) -> dict[str, str]:
    """Return id -> label for the pick-lists, with shared storage named as such."""
    shared = shared_storage_names(resources)
    choices: dict[str, str] = {}
    for storage_id in tracked_storage_ids(resources):
        name = storage_name(storage_id)
        choices[storage_id] = f"{name} (shared)" if name in shared else storage_id
    return choices


def merge_shared_selection(
    selection: list[str],
    shared: set[str],
    preferred_node: str | None,
) -> tuple[list[str], dict[str, str], list[str]]:
    """
    Turn the per-node ids of shared storages in a selection into one each.

    Returns the new selection, which old id keeps its history for each new
    id (the one on `preferred_node` where picked, otherwise the first picked),
    and the old ids that are dropped. Ids of local storage, and ids already
    in the shared form, pass through untouched and in order.
    """
    new_selection: list[str] = []
    keepers: dict[str, str] = {}
    dropped: list[str] = []
    per_name: dict[str, list[str]] = {}

    for storage_id in selection:
        name = storage_name(storage_id)
        if is_shared_storage_id(storage_id) or name not in shared:
            if storage_id not in new_selection:
                new_selection.append(storage_id)
            continue
        per_name.setdefault(name, []).append(storage_id)

    for name, old_ids in per_name.items():
        new_id = shared_storage_id(name)
        keeper = next(
            (old for old in old_ids if storage_node(old) == preferred_node),
            old_ids[0],
        )
        keepers[new_id] = keeper
        dropped.extend(old for old in old_ids if old != keeper)
        if new_id not in new_selection:
            new_selection.append(new_id)

    return new_selection, keepers, dropped
