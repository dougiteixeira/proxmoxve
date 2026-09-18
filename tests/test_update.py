# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for the per-node update entity."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from homeassistant.const import CONF_HOST, CONF_PORT
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


HOST = "pve.example.invalid"


def _entity(
    update_data: object,
    node_version: object = "9.0.6",
    host: str = HOST,
) -> ProxmoxUpdateEntity:
    """Build an update entity over the given update and node data."""
    coordinator = MagicMock()
    coordinator.data = update_data
    coordinator.last_update_success = True
    coordinator.config_entry = SimpleNamespace(data={CONF_HOST: host, CONF_PORT: 8006})
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
    # The version each package replaces is kept for the release notes.
    assert [entry["old"] for entry in data.packages] == [
        "9.0.8",
        "6.14.8-2",
        "9.0.6",
        "3.5.1-1",
    ]


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


# What a plain node with the bundled Ceph libraries waiting looks like:
# the release moves from 9.2.11 to 9.2.20, and Ceph's own packages move
# to 19.2.6 - a version that has nothing to do with the Proxmox release.
CEPH_PENDING = [
    {
        "Package": "pve-manager",
        "Title": "Proxmox Virtual Environment Management Tools",
        "Version": "9.2.20",
        "OldVersion": "9.2.11",
        "Origin": "Proxmox",
    },
    {
        "Package": "ceph-common",
        "Title": "common utilities to mount and interact with a ceph storage cluster",
        "Version": "19.2.6-pve4",
        "OldVersion": "19.2.3-pve1",
        "Origin": "Proxmox",
    },
    {
        "Package": "librados2",
        "Title": "RADOS distributed object store client library",
        "Version": "19.2.6-pve4",
        "OldVersion": "19.2.3-pve1",
        "Origin": "Proxmox",
    },
]


def test_the_release_comes_from_pve_manager_not_from_ceph() -> None:
    """
    Test the reported problem: the node looked like it was going to 19.2.6.

    The latest version used to be the highest among Proxmox's pending
    packages, and Proxmox ships the Ceph client libraries, which are at
    19.x. `pve-manager` is what `pveversion` reports, so it is the one
    that says where the release is going.
    """
    info = update_version("9.2.11", parse_updates(CEPH_PENDING, "pve").packages)

    assert info.latest_version == "9.2.20"
    assert info.latest_version_id == "9.2.20-p3-d0"
    assert info.proxmox_updates == 3


def test_without_a_pending_release_the_version_stays() -> None:
    """
    Test Ceph alone moves nothing: the release is where it was.

    The id still differs from the installed version, so Home Assistant
    keeps showing that something is pending.
    """
    info = update_version("9.2.11", parse_updates(CEPH_PENDING[1:], "pve").packages)

    assert info.latest_version == "9.2.11"
    assert info.latest_version_id == "9.2.11-p2-d0"
    assert info.latest_version_id != "9.2.11"


def test_update_version_uses_the_release_package() -> None:
    """Test the id carries the release and both pending counts."""
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
        "4 package update(s) pending: 3 from Proxmox, 1 from other sources. "
        "The newest pending Proxmox version is 9.0.10."
    )


def test_the_summary_stays_under_what_home_assistant_keeps() -> None:
    """
    Test the one line fits, whatever the host is called.

    Home Assistant cuts `release_summary` at 255 characters. The node's
    address used to be in this text, and a long host name pushed the cut
    into the middle of the link.
    """
    entity = _entity(parse_updates(PENDING, "pve"), host="a" * 200)

    assert entity.release_summary is not None
    assert len(entity.release_summary) <= 255


def test_the_release_url_points_at_the_node_update_panel() -> None:
    """Test what Home Assistant offers as the release announcement."""
    entity = _entity(parse_updates(PENDING, "pve"))

    assert entity.release_url == (f"https://{HOST}:8006/#v1:0:=node%2Fpve:4:31::::::")


def test_no_release_url_without_data() -> None:
    """Test a node whose updates could not be read offers no link."""
    assert _entity(None).release_url is None


def test_the_release_notes_list_the_packages() -> None:
    """
    Test the notes say which package moves from which version to which.

    Proxmox's own packages first, each group alphabetically, as the
    coordinator sorted them; the counts are the first line.
    """
    entity = _entity(parse_updates(PENDING, "pve"))
    notes = entity.release_notes()

    assert notes is not None
    assert notes.splitlines()[0] == entity.release_summary
    assert "**Proxmox**" in notes
    assert "**Other**" in notes
    assert (
        "- Proxmox VE base library (`libpve-common-perl`) — `9.0.8` → `9.0.9`" in notes
    )
    assert (
        "- Proxmox Virtual Environment Management Tools (`pve-manager`) "
        "— `9.0.6` → `9.0.10`" in notes
    )
    assert (
        "- Secure Sockets Layer toolkit - cryptographic utility (`openssl`) "
        "— `3.5.1-1` → `3.5.1-1+deb13u1`" in notes
    )
    # Proxmox's packages are listed before the rest.
    assert notes.index("**Proxmox**") < notes.index("**Other**")


def test_the_release_notes_leave_out_an_empty_group() -> None:
    """Test a pending set without Proxmox packages has no Proxmox heading."""
    notes = _entity(parse_updates([PENDING[0]], "pve")).release_notes()

    assert notes is not None
    assert "**Proxmox**" not in notes
    assert "**Other**" in notes


def test_a_debian_version_is_not_read_as_markdown() -> None:
    """
    Test the reported display: a tilde struck the versions through.

    A Debian version carries a tilde, and one tilde is enough to open a
    strikethrough - so `1:9.20.26-1~deb13u1 -> 1:9.20.29-1~deb13u1` came
    out with everything between the two tildes struck out. Code spans keep
    both versions as they are; a title that holds markdown characters is
    escaped.
    """
    pending = [
        {
            "Package": "bind9-dnsutils",
            "Title": "Clients provided with BIND 9 *and* _more_",
            "Version": "1:9.20.29-1~deb13u1",
            "OldVersion": "1:9.20.26-1~deb13u1",
            "Origin": "Debian",
        }
    ]
    notes = _entity(parse_updates(pending, "pve")).release_notes()

    assert notes is not None
    assert "`1:9.20.26-1~deb13u1` → `1:9.20.29-1~deb13u1`" in notes
    assert r"Clients provided with BIND 9 \*and\* \_more\_" in notes


def test_a_package_apt_would_install_says_it_is_new() -> None:
    """
    Test a package with no previous version is not shown as half a line.

    A new kernel brings its own versioned package names along, so apt
    reports them without an `OldVersion` - and `proxmox-headers-7.0.14-17-pve
    - 7.0.14-17` read like the rest of the line had gone missing.
    """
    pending = [{key: value for key, value in PENDING[1].items() if key != "OldVersion"}]
    notes = _entity(parse_updates(pending, "pve")).release_notes()

    assert notes is not None
    assert (
        "- Proxmox Virtual Environment Management Tools (`pve-manager`) "
        "— new: `9.0.10`" in notes
    )


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
    # Nothing pending, but the panel is still where it is.
    assert entity.release_url is not None


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
