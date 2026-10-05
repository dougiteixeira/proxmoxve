# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for reading a node's hardware addresses out of its interface list."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.proxmoxve import DOMAIN
from custom_components.proxmoxve.const import CONF_NODES
from custom_components.proxmoxve.coordinator import parse_mac_addresses

from .fake_api import NODE, FakeProxmox

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


async def test_two_nodes_that_report_the_same_address(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """
    Test one node keeps the shared address and the other goes without it.

    Reported upstream in #700: two nodes of a cluster carried the same
    permanent address - an onboard controller whose MAC lives in the
    board's flash, cloned along with the BIOS region - so one of them
    overrides it in its own configuration. The listing still names the
    port after the permanent address, so both nodes reported the same
    one, and Home Assistant refuses to give a connection to a second
    device of the same entry. That refusal used to fail the whole setup:
    a cluster with one such pair lost every entity it had.
    """
    for path, answer in list(fake_api.routes.items()):
        if path.startswith(f"nodes/{NODE}/"):
            fake_api.routes[path.replace(f"nodes/{NODE}/", "nodes/pve2/", 1)] = answer
    fake_api.routes["nodes"] = [
        *fake_api.routes["nodes"],
        {**fake_api.routes["nodes"][0], "node": "pve2", "id": "node/pve2"},
    ]
    fake_api.routes["cluster/resources"] = [
        *fake_api.routes["cluster/resources"],
        {
            **next(
                row
                for row in fake_api.routes["cluster/resources"]
                if row.get("type") == "node"
            ),
            "id": "node/pve2",
            "node": "pve2",
        },
    ]
    hass.config_entries.async_update_entry(
        current_entry, data={**current_entry.data, CONF_NODES: [NODE, "pve2"]}
    )

    await hass.config_entries.async_setup(current_entry.entry_id)
    await hass.async_block_till_done()

    assert current_entry.state is ConfigEntryState.LOADED
    dev_reg = dr.async_get(hass)
    devices = {
        node: dev_reg.async_get_device_by_identifier(
            (DOMAIN, f"{current_entry.entry_id}_NODE_{node}"), current_entry.entry_id
        )
        for node in (NODE, "pve2")
    }
    assert all(device is not None for device in devices.values())
    # Two nodes, two devices: the connection used to pull the second
    # node's identifier onto the first node's device instead.
    assert devices[NODE].id != devices["pve2"].id
    macs = [
        {mac for kind, mac in device.connections if kind == dr.CONNECTION_NETWORK_MAC}
        for device in devices.values()
    ]
    # One of them has the addresses, the other has none of them - and
    # neither has an address the other holds.
    assert macs[0] & macs[1] == set()
    assert macs[0] or macs[1]
