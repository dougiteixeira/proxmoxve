# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for the per-node update entity."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from homeassistant.helpers.typing import UNDEFINED

from custom_components.proxmoxve.coordinator import is_proxmox_package, parse_updates
from custom_components.proxmoxve.update import (
    PROXMOX_UPDATE_NODE,
    ProxmoxUpdateEntity,
    latest_version,
    update_version,
)

# Shaped like `GET /nodes/<node>/apt/update`: one entry per pending package.
# The real response also carries Description, ChangeLogUrl, Arch, Section and
# Priority, none of which are read. Values here are invented.
PENDING = [
    {
        "Package": "openssl",
        "Title": "Secure Sockets Layer toolkit - cryptographic utility",
        "Version": "3.5.1-1+deb13u1",
        "OldVersion": "3.5.1-1",
        "Origin": "Debian",
    },
    {
        "Package": "pve-manager",
        "Title": "Proxmox Virtual Environment Management Tools",
        "Version": "9.0.10",
        "OldVersion": "9.0.6",
        "Origin": "Proxmox",
    },
    {
        "Package": "libpve-common-perl",
        "Title": "Proxmox VE base library",
        "Version": "9.0.9",
        "OldVersion": "9.0.8",
        "Origin": "Proxmox",
    },
    {
        "Package": "proxmox-kernel-6.14",
        "Title": "Proxmox Kernel Image (signed)",
        "Version": "6.14.11-2",
        "OldVersion": "6.14.8-2",
        "Origin": "Proxmox",
    },
]


def _entity(
    update_data: object,
    node_version: object = "9.0.6",
) -> ProxmoxUpdateEntity:
    """Build an update entity over the given update and node data."""
    coordinator = MagicMock()
    coordinator.data = update_data
    coordinator.last_update_success = True
    node_coordinator = MagicMock()
    node_coordinator.data = SimpleNamespace(version=node_version)
    return ProxmoxUpdateEntity(
        coordinator=coordinator,
        node_coordinator=node_coordinator,
        info_device={"configuration_url": "https://pve.example.invalid:8006/"},
        description=PROXMOX_UPDATE_NODE,
        unique_id="test_update",
    )


def test_proxmox_packages_are_told_apart() -> None:
    """Test the origin, the name prefix and the title each identify Proxmox."""
    assert is_proxmox_package({"Package": "pve-manager"})
    assert is_proxmox_package({"Package": "libpve-common-perl"})
    assert is_proxmox_package({"Package": "qemu-server", "Origin": "Proxmox"})
    assert is_proxmox_package({"Package": "x", "Title": "Proxmox Kernel Image"})
    assert not is_proxmox_package({"Package": "openssl", "Origin": "Debian"})


def test_parse_updates_counts_and_orders() -> None:
    """Test the packages are counted per origin and Proxmox's come first."""
    data = parse_updates(PENDING, "pve")

    assert data.total == 4
    assert data.update is True
    assert data.proxmox_updates == 3
    assert data.other_updates == 1
    assert [entry["package"] for entry in data.packages] == [
        "libpve-common-perl",
        "proxmox-kernel-6.14",
        "pve-manager",
        "openssl",
    ]
    # The flat list the existing sensor attribute carries is unchanged.
    assert data.updates_list == sorted(
        f"{entry['Title']} - {entry['Version']}" for entry in PENDING
    )


def test_parse_updates_without_proxmox_packages() -> None:
    """Test a pending set of Debian packages only."""
    data = parse_updates([PENDING[0]], "pve")

    assert data.total == 1
    assert data.proxmox_updates == 0


def test_parse_updates_nothing_pending() -> None:
    """Test an up-to-date node reads as such."""
    data = parse_updates([], "pve")

    assert data.total == 0
    assert data.update is False
    assert data.packages == []


def test_latest_version_ignores_debian_suffixes() -> None:
    """Test `-pve1`-style suffixes do not take part in the comparison."""
    assert latest_version(["9.0.6", "9.0.10-1", "6.14.11-2"]) == "9.0.10"


def test_latest_version_survives_a_version_packaging_cannot_read() -> None:
    """Test an epoch such as `2:1.0` sorts lowest instead of raising."""
    assert latest_version(["9.0.6", "2:1.0"]) == "9.0.6"


def test_update_version_matches_the_core_integration() -> None:
    """Test the id carries the release and both pending counts, like core."""
    info = update_version("9.0.6", parse_updates(PENDING, "pve").packages)

    assert info.latest_version == "9.0.10"
    assert info.latest_version_id == "9.0.10-p3-d1"
    assert info.total_updates == 4
    assert info.proxmox_updates == 3
    assert info.other_updates == 1


def test_entity_reports_the_pending_release() -> None:
    """Test the entity reads exactly like the core integration's."""
    entity = _entity(parse_updates(PENDING, "pve"))

    assert entity.available
    assert entity.installed_version == "9.0.6"
    assert entity.latest_version == "9.0.10-p3-d1"
    assert entity.release_summary == (
        "A total of 4 package update(s) are pending installation: of these 3 "
        "relate to Proxmox and 1 to other updates. Please visit the "
        "[Proxmox VE node](https://pve.example.invalid:8006/) for details on "
        "the pending updates and to upgrade to 9.0.10."
    )
    assert entity.release_notes() == entity.release_summary


def test_entity_shows_an_update_for_other_packages_alone() -> None:
    """
    Test pending Debian packages still count as an update.

    The release stays the same, so the counts in the id have to make the
    difference to the installed version - Home Assistant compares the two.
    """
    entity = _entity(parse_updates([PENDING[0]], "pve"))

    assert entity.installed_version == "9.0.6"
    assert entity.latest_version == "9.0.6-p0-d1"
    assert entity.latest_version != entity.installed_version


def test_entity_up_to_date() -> None:
    """Test no pending packages means latest equals installed."""
    entity = _entity(parse_updates([], "pve"))

    assert entity.latest_version == entity.installed_version == "9.0.6"
    assert entity.release_summary is None
    assert entity.release_notes() is None


def test_entity_unavailable_without_permission() -> None:
    """Test a node whose apt/update could not be read leaves the entity unavailable."""
    entity = _entity(SimpleNamespace(total=UNDEFINED, packages=[]))

    assert not entity.available
    assert entity.latest_version is None


def test_entity_without_node_version() -> None:
    """Test a missing node version reads as unknown, like core, and still compares."""
    entity = _entity(parse_updates(PENDING, "pve"), node_version=UNDEFINED)

    assert entity.installed_version == "unknown"
    assert entity.latest_version == "9.0.10-p3-d1"
