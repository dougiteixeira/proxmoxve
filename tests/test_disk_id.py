"""Tests for disk identifier resolution."""

from custom_components.proxmoxve.disk import (
    colliding_disk_wwns,
    disk_matches_id,
    resolve_disk_id,
)


def test_resolve_disk_id_prefers_unique_wwn():
    """Prefer WWN when it is present and usable."""
    disk = {
        "wwn": "eui.0025385811b0cf1d",
        "serial": "S4EVNX0R806063Y",
        "by_id_link": "/dev/disk/by-id/nvme-Samsung_S4EVNX0R806063Y",
        "devpath": "/dev/nvme0n1",
    }
    assert resolve_disk_id(disk) == "eui.0025385811b0cf1d"


def test_resolve_disk_id_skips_unknown_wwn():
    """Skip literal unknown WWN and fall back to serial."""
    disk = {
        "wwn": "unknown",
        "serial": "ABCDEF123456",
        "by_id_link": "/dev/disk/by-id/usb-Flash_ABCDEF123456",
        "devpath": "/dev/sda",
    }
    assert resolve_disk_id(disk) == "ABCDEF123456"


def test_resolve_disk_id_skips_empty_wwn():
    """Skip empty WWN and fall back to serial."""
    disk = {
        "wwn": "",
        "serial": "SERIALONLY",
        "devpath": "/dev/sdb",
    }
    assert resolve_disk_id(disk) == "SERIALONLY"


def test_resolve_disk_id_falls_back_to_by_id_then_devpath():
    """Fall back through by-id link to devpath when needed."""
    assert (
        resolve_disk_id(
            {
                "wwn": "unknown",
                "by_id_link": "/dev/disk/by-id/ata-DISK",
                "devpath": "/dev/sdc",
            }
        )
        == "/dev/disk/by-id/ata-DISK"
    )
    assert resolve_disk_id({"devpath": "/dev/sdd"}) == "/dev/sdd"


def test_resolve_disk_id_uses_serial_when_wwn_collides():
    """Use serial when the preferred WWN is duplicated on the node."""
    disks = [
        {
            "devpath": "/dev/sda",
            "serial": "6c81f660f9a626002a06a61d5b146759",
            "by_id_link": "/dev/disk/by-id/scsi-36c81f660f9a626002a06a61d5b146759",
            "wwn": "0x6c81f660f9a62600",
        },
        {
            "devpath": "/dev/sdb",
            "serial": "6c81f660f9a626002a06a41d3c93cfa2",
            "by_id_link": "/dev/disk/by-id/scsi-36c81f660f9a626002a06a41d3c93cfa2",
            "wwn": "0x6c81f660f9a62600",
        },
    ]
    colliding = colliding_disk_wwns(disks)
    assert colliding == {"0x6c81f660f9a62600"}
    ids = [resolve_disk_id(disk, colliding_wwns=colliding) for disk in disks]
    assert ids == [
        "6c81f660f9a626002a06a61d5b146759",
        "6c81f660f9a626002a06a41d3c93cfa2",
    ]


def test_colliding_disk_wwns_ignores_unknown_and_unique():
    """Only non-unknown duplicated WWNs are reported as colliding."""
    disks = [
        {"wwn": "unknown", "serial": "a"},
        {"wwn": "unknown", "serial": "b"},
        {"wwn": "eui.unique", "serial": "c"},
        {"wwn": "eui.dup", "serial": "d"},
        {"wwn": "eui.dup", "serial": "e"},
    ]
    assert colliding_disk_wwns(disks) == {"eui.dup"}


def test_disk_matches_id_ignores_unknown_wwn():
    """Do not match resource_id against a literal unknown WWN."""
    disk = {
        "wwn": "unknown",
        "serial": "ABCDEF123456",
        "by_id_link": "/dev/disk/by-id/usb-Flash_ABCDEF123456",
        "devpath": "/dev/sda",
    }
    assert not disk_matches_id(disk, "unknown")
    assert disk_matches_id(disk, "ABCDEF123456")
    assert disk_matches_id(disk, "/dev/disk/by-id/usb-Flash_ABCDEF123456")
    assert disk_matches_id(disk, "/dev/sda")


def test_disk_matches_id_by_wwn():
    """Match a usable WWN resource id."""
    disk = {
        "wwn": "eui.0025385811b0cf1d",
        "serial": "S4EVNX0R806063Y",
        "devpath": "/dev/nvme0n1",
    }
    assert disk_matches_id(disk, "eui.0025385811b0cf1d")
    assert not disk_matches_id(disk, "other")
