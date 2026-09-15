# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for the cluster at a glance."""

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import UNDEFINED
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.proxmoxve.coordinator import parse_cluster_summary

from .fake_api import FakeProxmox
from .test_setup_full import _setup, _state

# Shaped like `cluster/resources`: two nodes of different size, one of them
# offline, three guests of which one is a template. Values invented.
LISTING = [
    {
        "type": "node",
        "node": "big",
        "status": "online",
        "cpu": 0.5,
        "maxcpu": 16,
        "mem": 64,
        "maxmem": 128,
    },
    {
        "type": "node",
        "node": "small",
        "status": "online",
        "cpu": 1.0,
        "maxcpu": 4,
        "mem": 8,
        "maxmem": 16,
    },
    {
        "type": "node",
        "node": "off",
        "status": "offline",
        "cpu": 0,
        "maxcpu": 8,
        "mem": 0,
        "maxmem": 32,
    },
    {"type": "qemu", "vmid": 100, "status": "running"},
    {"type": "qemu", "vmid": 101, "status": "stopped"},
    {"type": "qemu", "vmid": 9000, "status": "stopped", "template": 1},
    {"type": "lxc", "vmid": 200, "status": "running"},
    {"type": "storage", "id": "storage/big/local"},
]


def test_nodes_and_guests_are_counted() -> None:
    """Test the counts, with the template left out and the offline node named."""
    data = parse_cluster_summary(LISTING)

    assert (data.nodes_total, data.nodes_online, data.nodes_offline) == (3, 2, ["off"])
    assert (data.qemu_total, data.qemu_running) == (2, 1)
    assert (data.lxc_total, data.lxc_running) == (1, 1)


def test_cpu_is_weighted_by_cores_and_memory_summed_over_online_nodes() -> None:
    """
    Test a busy small node does not count like a busy big one.

    16 cores at 50% and 4 cores at 100% is 12 of 20 cores busy: 60%, not the
    75% a plain average of the two figures would say. The offline node
    contributes nothing to either figure.
    """
    data = parse_cluster_summary(LISTING)

    assert data.cpu == pytest.approx(0.6)
    assert (data.memory_used, data.memory_total) == (72, 144)


def test_an_empty_or_odd_listing() -> None:
    """Test nothing to add up yields zeros and no ratio."""
    data = parse_cluster_summary([])
    assert data.nodes_total == 0
    assert data.cpu is UNDEFINED
    assert data.memory_total is UNDEFINED
    assert parse_cluster_summary("nonsense").qemu_total == 0


async def test_the_cluster_device_carries_the_summary(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test every setup gets the summary on the cluster device."""
    await _setup(hass, current_entry)
    entry_id = current_entry.entry_id

    online = _state(hass, current_entry, f"{entry_id}_cluster_nodes_online", "sensor")
    assert online.state == "1"
    assert online.attributes["nodes_total"] == 1
    running = _state(hass, current_entry, f"{entry_id}_cluster_qemu_running", "sensor")
    assert running.state == "1"
    cpu = _state(hass, current_entry, f"{entry_id}_cluster_cpu", "sensor")
    assert float(cpu.state) == pytest.approx(1.35)
