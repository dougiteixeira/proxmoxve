# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""
Tests for the pressure stall sensors of a guest, and a VM's host memory.

Asked for upstream in discussion #685: "RAM used" says little on Linux,
because the kernel keeps what it can. Proxmox reports the kernel's
pressure stall information per guest on the status read the integration
already makes, so this costs no extra request - and it answers for a
Windows VM as well, since it is the host's view of that VM's cgroup.

Containers report the averages as strings ("0.46"), VMs as numbers, and
Proxmox VE 8 does not report them at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import UNDEFINED

from custom_components.proxmoxve.coordinator import parse_pressure

from .test_setup_full import _setup

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from .fake_api import FakeProxmox

PRESSURE_KEYS = (
    "pressure_cpu_some",
    "pressure_cpu_full",
    "pressure_io_some",
    "pressure_io_full",
    "pressure_memory_some",
    "pressure_memory_full",
)


def test_a_vm_reports_numbers() -> None:
    """Test what a VM sends: plain numbers."""
    pressure = parse_pressure(
        {
            "pressurecpusome": 0.12,
            "pressurecpufull": 0,
            "pressureiosome": 0.4,
            "pressureiofull": 0.1,
            "pressurememorysome": 1.5,
            "pressurememoryfull": 0.75,
        }
    )

    assert pressure == {
        "pressure_cpu_some": 0.12,
        "pressure_cpu_full": 0.0,
        "pressure_io_some": 0.4,
        "pressure_io_full": 0.1,
        "pressure_memory_some": 1.5,
        "pressure_memory_full": 0.75,
    }


def test_a_container_reports_strings() -> None:
    """
    Test what a container sends: the same averages as strings.

    Checked against a live cluster - the schema says `number` for both, the
    API sends `"0.46"` for a container.
    """
    pressure = parse_pressure(
        {
            "pressurecpusome": "0.46",
            "pressurecpufull": "0.00",
            "pressureiosome": "0.00",
            "pressureiofull": "0.00",
            "pressurememorysome": "0.00",
            "pressurememoryfull": "0.00",
        }
    )

    assert pressure["pressure_cpu_some"] == 0.46
    assert pressure["pressure_memory_full"] == 0.0


def test_a_proxmox_that_does_not_report_pressure() -> None:
    """Test Proxmox VE 8 leaves every one of them unknown, not zero."""
    pressure = parse_pressure({"status": "running"})

    assert set(pressure) == set(PRESSURE_KEYS)
    assert all(value is UNDEFINED for value in pressure.values())


def test_a_value_that_is_not_a_number() -> None:
    """Test nonsense is unknown rather than an exception on every poll."""
    pressure = parse_pressure({"pressurecpusome": "n/a", "pressureiosome": None})

    assert pressure["pressure_cpu_some"] is UNDEFINED
    assert pressure["pressure_io_some"] is UNDEFINED


@pytest.mark.parametrize(
    ("entity_id", "expected"),
    [
        ("sensor.qemu_vm_test_101_101_cpu_pressure", "0.12"),
        ("sensor.qemu_vm_test_101_101_io_pressure", "0.4"),
        ("sensor.qemu_vm_test_101_101_memory_pressure", "0.0"),
        ("sensor.lxc_lxc_test_100_100_cpu_pressure", "0.46"),
        ("sensor.lxc_lxc_test_100_100_memory_pressure", "0.0"),
    ],
)
async def test_the_sensors_carry_what_the_guest_reports(
    hass: HomeAssistant,
    fake_api: FakeProxmox,
    current_entry: MockConfigEntry,
    entity_id: str,
    expected: str,
) -> None:
    """Test the values reach the entities, for a VM and for a container."""
    await _setup(hass, current_entry)
    registry = er.async_get(hass)
    entry = registry.async_get(entity_id)
    assert entry is not None, f"{entity_id} was not created"

    # Diagnostic and off by default: eleven more entities per guest otherwise.
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert entry.entity_category is EntityCategory.DIAGNOSTIC
    assert entry.unit_of_measurement == PERCENTAGE

    registry.async_update_entity(entity_id, disabled_by=None)
    await hass.config_entries.async_reload(current_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == expected


async def test_a_vm_reports_the_memory_it_costs_the_host(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """
    Test the VM's memory as the host sees it, which is the capacity figure.

    More than the guest reports using: device models, migration buffers and
    the like. Containers have no equivalent, so they have no such sensor.
    """
    await _setup(hass, current_entry)
    registry = er.async_get(hass)
    entity_id = "sensor.qemu_vm_test_101_101_memory_used_on_host"

    entry = registry.async_get(entity_id)
    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION

    registry.async_update_entity(entity_id, disabled_by=None)
    await hass.config_entries.async_reload(current_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state is not None
    assert float(state.state) == pytest.approx(3.75, abs=0.01)
    assert registry.async_get("sensor.lxc_lxc_test_100_100_memory_used_on_host") is None
