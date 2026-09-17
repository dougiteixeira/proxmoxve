# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""
Tests for a guest's addresses and whether the QEMU guest agent answers.

Upstream #140 asked for both. A VM reports through the agent
(`agent/network-get-interfaces`), a container through its own
`lxc/{vmid}/interfaces`; loopback and link-local addresses are noise.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import UNDEFINED
from proxmoxer.core import ResourceException
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.proxmoxve import DOMAIN
from custom_components.proxmoxve.const import COORDINATORS, ProxmoxType
from custom_components.proxmoxve.coordinator import parse_guest_addresses

from .fake_api import NODE, FakeProxmox, qemu_status
from .test_setup_full import _setup, _state


def test_a_vm_shows_its_first_ipv4_and_keeps_the_rest() -> None:
    """Test loopback and link-local are dropped; IPv4 wins for the state."""
    parsed = parse_guest_addresses(
        ProxmoxType.QEMU,
        {
            "result": [
                {"name": "lo", "ip-addresses": [{"ip-address": "127.0.0.1"}]},
                {
                    "name": "ens18",
                    "ip-addresses": [
                        {"ip-address": "fe80::1"},
                        {"ip-address": "2001:db8::10"},
                        {"ip-address": "192.0.2.10"},
                    ],
                },
            ]
        },
    )

    assert parsed["ip_address"] == "192.0.2.10"
    assert parsed["ip_addresses"] == ["2001:db8::10", "192.0.2.10"]
    assert parsed["interfaces"] == {"ens18": ["2001:db8::10", "192.0.2.10"]}


def test_a_container_reads_its_inet_strings_without_the_prefix() -> None:
    """Test the container shape: `inet`/`inet6` with a prefix length."""
    parsed = parse_guest_addresses(
        ProxmoxType.LXC,
        [
            {"name": "lo", "inet": "127.0.0.1/8", "inet6": "::1/128"},
            {"name": "eth0", "inet": "192.0.2.20/24", "inet6": "fe80::2/64"},
        ],
    )

    assert parsed["ip_address"] == "192.0.2.20"
    assert parsed["interfaces"] == {"eth0": ["192.0.2.20"]}


def test_only_ipv6_is_shown_when_there_is_no_ipv4() -> None:
    """Test a v6-only guest still has an address to show."""
    parsed = parse_guest_addresses(
        ProxmoxType.LXC, [{"name": "eth0", "inet6": "2001:db8::20/64"}]
    )
    assert parsed["ip_address"] == "2001:db8::20"


def test_nothing_readable_is_unknown() -> None:
    """Test a failed read is undefined, an empty one has an empty list."""
    assert parse_guest_addresses(ProxmoxType.QEMU, None)["ip_address"] is UNDEFINED
    empty = parse_guest_addresses(ProxmoxType.QEMU, {"result": []})
    assert empty["ip_address"] is UNDEFINED
    assert empty["ip_addresses"] == []


async def test_the_vm_and_the_container_get_an_address_sensor(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test both guests report their address with the rest as attributes."""
    await _setup(hass, current_entry)
    entry_id = current_entry.entry_id

    vm = _state(hass, current_entry, f"{entry_id}_101_ip_address", "sensor")
    assert vm.state == "192.0.2.10"
    assert vm.attributes["ip_addresses"] == ["192.0.2.10", "2001:db8::10"]
    assert vm.attributes["interfaces"] == {"ens18": ["192.0.2.10", "2001:db8::10"]}
    ct = _state(hass, current_entry, f"{entry_id}_100_ip_address", "sensor")
    assert ct.state == "192.0.2.20"


async def test_the_guest_agent_sensor_says_whether_the_agent_answers(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test on while the agent answers, off once it does not."""
    await _setup(hass, current_entry)
    entry_id = current_entry.entry_id
    assert (
        _state(
            hass, current_entry, f"{entry_id}_101_agent_running", "binary_sensor"
        ).state
        == "on"
    )

    fake_api.routes[f"nodes/{NODE}/qemu/101/agent/network-get-interfaces"] = (
        ResourceException(
            500, "Internal Server Error", "QEMU guest agent is not running"
        )
    )
    coordinator = current_entry.runtime_data[COORDINATORS]["qemu_101"]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.data.agent_running is False
    assert (
        _state(
            hass, current_entry, f"{entry_id}_101_agent_running", "binary_sensor"
        ).state
        == "off"
    )
    # The address is gone with the agent; the sensor stays, reads unknown.
    assert coordinator.data.ip_address is UNDEFINED


async def test_a_vm_without_the_agent_configured_gets_no_agent_sensor(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test `agent` absent from the VM's status means no sensor, no agent call."""
    status = qemu_status(101, "vm-test-101")
    del status["agent"]
    fake_api.routes[f"nodes/{NODE}/qemu/101/status/current"] = status
    await _setup(hass, current_entry)

    data = current_entry.runtime_data[COORDINATORS]["qemu_101"].data
    assert data.agent_running is UNDEFINED
    registry = er.async_get(hass)
    assert (
        registry.async_get_entity_id(
            "binary_sensor", DOMAIN, f"{current_entry.entry_id}_101_agent_running"
        )
        is None
    )
    assert f"nodes/{NODE}/qemu/101/agent/network-get-interfaces" not in fake_api.paths()


async def test_a_refused_agent_read_leaves_the_agent_state_unknown(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test a 403 says nothing about the agent - the repair says what is missing."""
    forbidden = ResourceException(403, "Forbidden", "Permission check failed")
    fake_api.routes[f"nodes/{NODE}/qemu/101/agent/network-get-interfaces"] = forbidden
    fake_api.routes[f"nodes/{NODE}/qemu/101/agent/get-fsinfo"] = forbidden
    await _setup(hass, current_entry)

    data = current_entry.runtime_data[COORDINATORS]["qemu_101"].data
    assert data.agent_running is UNDEFINED
    assert data.ip_address is UNDEFINED
