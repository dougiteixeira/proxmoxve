# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for reading a node's hardware addresses out of its interface list."""

from custom_components.proxmoxve.coordinator import parse_mac_addresses

# Shaped like `GET /nodes/<node>/network`. Bridges carry the IP, physical
# ports carry systemd's names - one predictable, one built from the MAC.
# Addresses invented (locally administered range).
INTERFACES = [
    {
        "iface": "vmbr0",
        "type": "bridge",
        "bridge_ports": "nic0",
        "address": "192.0.2.10",
    },
    {"iface": "nic0", "type": "eth", "altnames": ["enp0s31f6", "enx02000a0b0c0d"]},
    {"iface": "nic1", "type": "eth", "altnames": ["enp179s0f0", "enx02000a0b0c0e"]},
    {"iface": "nic2", "type": "eth", "altnames": ["enp179s0f1"]},
]


def test_the_mac_based_altname_is_decoded() -> None:
    """Test each physical port with a MAC-based name yields its address."""
    assert parse_mac_addresses(INTERFACES) == ("02:00:0a:0b:0c:0d", "02:00:0a:0b:0c:0e")


def test_only_physical_ports_count() -> None:
    """Test a bridge with an `enx`-looking altname would still be skipped."""
    interfaces = [{"iface": "vmbr0", "type": "bridge", "altnames": ["enx02000a0b0c0d"]}]

    assert parse_mac_addresses(interfaces) == ()


def test_the_same_address_twice_is_reported_once() -> None:
    """Test a port listed twice does not double its address."""
    port = {"iface": "nic0", "type": "eth", "altnames": ["enx02000a0b0c0d"]}

    assert parse_mac_addresses([port, port]) == ("02:00:0a:0b:0c:0d",)


def test_malformed_input() -> None:
    """Test anything not shaped like the listing yields no addresses."""
    assert parse_mac_addresses(None) == ()
    assert parse_mac_addresses("nonsense") == ()
    assert (
        parse_mac_addresses([{"type": "eth"}, {"type": "eth", "altnames": None}]) == ()
    )
    assert parse_mac_addresses([{"type": "eth", "altnames": ["enxZZ", 42]}]) == ()
