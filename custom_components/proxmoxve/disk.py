"""Helpers for stable Proxmox disk identifiers."""

from __future__ import annotations

from typing import Any


def resolve_disk_id(
    disk: dict[str, Any],
    *,
    colliding_wwns: set[str] | None = None,
) -> str:
    """Return a stable disk identifier.

    Prefer WWN when it is present, not ``unknown``, and not duplicated among
    disks on the same node. Fall back to serial, then by-id link, then devpath.
    """
    wwn = disk.get("wwn")
    if (
        wwn
        and wwn != "unknown"
        and (colliding_wwns is None or wwn not in colliding_wwns)
    ):
        return wwn
    if serial := disk.get("serial"):
        return serial
    if by_id := disk.get("by_id_link"):
        return by_id
    return disk["devpath"]


def colliding_disk_wwns(disks: list[dict[str, Any]]) -> set[str]:
    """Return WWNs that appear more than once in the disk list."""
    seen: set[str] = set()
    colliding: set[str] = set()
    for disk in disks:
        wwn = disk.get("wwn")
        if not wwn or wwn == "unknown":
            continue
        if wwn in seen:
            colliding.add(wwn)
        else:
            seen.add(wwn)
    return colliding


def disk_matches_id(disk: dict[str, Any], resource_id: str) -> bool:
    """Return True if disk corresponds to the given resource id."""
    wwn = disk.get("wwn")
    if wwn and wwn != "unknown" and wwn == resource_id:
        return True
    if disk.get("by_id_link") == resource_id:
        return True
    if disk.get("serial") == resource_id:
        return True
    return disk.get("devpath") == resource_id
