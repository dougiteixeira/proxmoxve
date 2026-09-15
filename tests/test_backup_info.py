# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for reporting which guests no backup job covers."""

from custom_components.proxmoxve.const import ProxmoxType
from custom_components.proxmoxve.coordinator import parse_backup_info

# `GET /cluster/backup-info/not-backed-up` returns one entry per guest that no
# backup job covers, with `vmid`, `name` and `type`. Values here are invented.
NOT_COVERED = [
    {"vmid": 101, "name": "database", "type": "qemu"},
    {"vmid": 205, "name": "dns", "type": "lxc"},
]


def test_everything_is_covered() -> None:
    """
    Test an empty response is the good case.

    The endpoint lists what is *not* covered, so a cluster where every guest
    has a backup job returns nothing at all.
    """
    data = parse_backup_info([])

    assert data.type == ProxmoxType.BackupInfo
    assert data.guests_without_backup == 0
    assert data.guests == []


def test_guests_are_counted_and_listed() -> None:
    """Test each uncovered guest is counted and carried as an attribute."""
    data = parse_backup_info(NOT_COVERED)

    assert data.guests_without_backup == 2
    assert data.guests == [
        {"vmid": 101, "type": "qemu", "name": "database"},
        {"vmid": 205, "type": "lxc", "name": "dns"},
    ]


def test_a_guest_without_a_name() -> None:
    """Test a guest that reports no name is still counted."""
    data = parse_backup_info([{"vmid": 300, "type": "qemu"}])

    assert data.guests_without_backup == 1
    assert data.guests == [{"vmid": 300, "type": "qemu"}]


def test_malformed_entries_are_skipped() -> None:
    """Test anything without a vmid is not counted as a guest."""
    data = parse_backup_info(["nonsense", {"name": "no vmid"}, {"vmid": 7}])

    assert data.guests_without_backup == 1
    assert data.guests == [{"vmid": 7}]


def test_the_attribute_stays_serializable() -> None:
    """Test the guest list holds only values Home Assistant can store."""
    data = parse_backup_info(NOT_COVERED)

    for guest in data.guests:
        for key, value in guest.items():
            assert isinstance(key, str)
            assert isinstance(value, (str, int))
