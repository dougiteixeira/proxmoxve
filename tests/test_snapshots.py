# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""
Tests for the snapshot count per guest.

Upstream #290 asked how many snapshots a VM has, next to the button that
takes one. Read from `nodes/{node}/{qemu|lxc}/{vmid}/snapshot`, whose
list always ends with a `current` pseudo entry that is no snapshot.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import UNDEFINED
from proxmoxer.core import ResourceException
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.proxmoxve import DOMAIN
from custom_components.proxmoxve.const import COORDINATORS
from custom_components.proxmoxve.coordinator import parse_snapshots

from .fake_api import NODE, FakeProxmox
from .test_setup_full import _setup


def test_the_current_entry_is_not_a_snapshot() -> None:
    """Test the pseudo entry is left out and the names come newest first."""
    parsed = parse_snapshots(
        [
            {"name": "old", "snaptime": 1_700_000_000},
            {"name": "new", "snaptime": 1_757_900_000, "description": "x"},
            {"name": "current", "running": 1},
        ]
    )

    assert parsed["snapshots"] == 2
    assert parsed["snapshot_names"] == ["new", "old"]
    assert parsed["snapshot_latest"].timestamp() == 1_757_900_000


def test_a_guest_without_snapshots_reads_zero() -> None:
    """Test only `current` means zero, not unknown."""
    parsed = parse_snapshots([{"name": "current", "digest": "abc"}])

    assert parsed["snapshots"] == 0
    assert parsed["snapshot_names"] == []
    assert parsed["snapshot_latest"] is None


def test_nonsense_reads_unknown() -> None:
    """Test a failed or odd read leaves the figures undefined."""
    assert parse_snapshots(None)["snapshots"] is UNDEFINED
    assert parse_snapshots({"data": 1})["snapshots"] is UNDEFINED


async def test_the_sensor_counts_the_snapshots_of_each_guest(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test the VM reads 2 with the names as attributes, the container 0."""
    await _setup(hass, current_entry)
    coordinators = current_entry.runtime_data[COORDINATORS]

    vm = coordinators["qemu_101"].data
    assert vm.snapshots == 2
    assert vm.snapshot_names == ["before-update", "clean-install"]
    assert vm.snapshot_latest.timestamp() == 1_757_900_000
    assert coordinators["lxc_100"].data.snapshots == 0

    registry = er.async_get(hass)
    entry_id = current_entry.entry_id
    for suffix in ("101_snapshots", "100_snapshots"):
        entity = registry.async_get(
            registry.async_get_entity_id("sensor", DOMAIN, f"{entry_id}_{suffix}")
        )
        assert entity is not None, suffix
        # Diagnostic and off by default: one more read per guest is worth
        # having, not worth showing to everyone.
        assert entity.disabled_by is er.RegistryEntryDisabler.INTEGRATION
        assert entity.entity_category is er.EntityCategory.DIAGNOSTIC


async def test_a_refused_snapshot_list_creates_no_sensor_and_no_repair(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test a guest whose snapshot list cannot be read still sets up as before."""
    fake_api.routes[f"nodes/{NODE}/qemu/101/snapshot"] = ResourceException(
        500, "Internal Server Error", "boom"
    )
    await _setup(hass, current_entry)

    data = current_entry.runtime_data[COORDINATORS]["qemu_101"].data
    assert data.snapshots is UNDEFINED
    assert data.status == "running"
    registry = er.async_get(hass)
    assert (
        registry.async_get_entity_id(
            "sensor", DOMAIN, f"{current_entry.entry_id}_101_snapshots"
        )
        is None
    )
