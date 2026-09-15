# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for the node's load average and a guest's share of the host."""

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import UNDEFINED
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.proxmoxve.const import COORDINATORS, ProxmoxType
from custom_components.proxmoxve.coordinator import (
    cpu_share_of_host,
    parse_load_average,
)

from .fake_api import FakeProxmox
from .test_setup_full import _setup, _state


def test_load_average_is_three_numbers() -> None:
    """Test the three strings Proxmox sends become three floats, in order."""
    assert parse_load_average(["3.82", "2.78", "2.07"]) == (3.82, 2.78, 2.07)


@pytest.mark.parametrize(
    "value",
    [None, "3.82", [], ["1", "2"], ["1", "2", "3", "4"], ["a", "b", "c"], [1, None, 3]],
)
def test_load_average_that_is_not_one(value: object) -> None:
    """Test anything not shaped as three numbers is no reading."""
    assert parse_load_average(value) is UNDEFINED


def test_a_guests_share_of_the_host() -> None:
    """
    Test the guest's cpu, relative to its own cores, is scaled to the node.

    A two-core guest at 50% is one core busy; on a twelve-thread node that
    is a twelfth of the host, which is what Proxmox's summary shows.
    """
    assert cpu_share_of_host(0.5, 2, 12) == pytest.approx(1 / 12)
    assert cpu_share_of_host(1.0, 12, 12) == 1.0
    assert cpu_share_of_host(0, 4, 8) == 0


@pytest.mark.parametrize(
    ("cpu", "guest_cpus", "node_cpus"),
    [
        (None, 2, 8),
        (0.5, None, 8),
        (0.5, 2, None),
        (0.5, 0, 8),
        (0.5, 2, 0),
        ("0.5", 2, 8),
        (True, 2, 8),
    ],
)
def test_a_share_that_cannot_be_computed(
    cpu: object, guest_cpus: object, node_cpus: object
) -> None:
    """Test a missing or nonsensical input yields no reading rather than a guess."""
    assert cpu_share_of_host(cpu, guest_cpus, node_cpus) is UNDEFINED


async def test_the_entities_carry_load_cores_and_host_share(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test the node reports its load, and the VM its cores and host share."""
    await _setup(hass, current_entry)
    entry_id = current_entry.entry_id

    load = _state(hass, current_entry, f"{entry_id}_pve_load_1m", "sensor")
    assert float(load.state) == 0.10

    cpu = _state(hass, current_entry, f"{entry_id}_101_cpu", "sensor")
    assert cpu.attributes["cpus"] == 4
    # 4.8% of 4 cores on an 8-thread node is 2.4% of the host. Disabled by
    # default, so the value is read off the coordinator rather than a state.
    vm = current_entry.runtime_data[COORDINATORS][f"{ProxmoxType.QEMU}_101"].data
    assert vm.cpu_of_host == pytest.approx(0.048 * 4 / 8)
    ct = current_entry.runtime_data[COORDINATORS][f"{ProxmoxType.LXC}_100"].data
    assert ct.cpus == 2
    assert ct.cpu_of_host == pytest.approx(0.0003 * 2 / 8)
