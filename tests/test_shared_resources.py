# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""
Tests for reading `cluster/resources` once per poll burst.

Every VM, container and storage coordinator, the cluster summary and
discovery used to read the same list themselves - forty identical
requests a minute on a modest cluster. Now the first one reads and the
rest take the result, for the TTL.
"""

import asyncio
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.proxmoxve.const import COORDINATORS
from custom_components.proxmoxve.coordinator import (
    RESOURCES_TTL,
    SharedResources,
    shared_resources,
)

from .fake_api import FakeProxmox
from .test_setup_full import _setup


async def test_setup_reads_the_resource_list_once_for_everyone(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test one read serves the guests, the storage, the summary and discovery."""
    await _setup(hass, current_entry)

    reads = [path for path in fake_api.paths() if path.startswith("cluster/resources")]
    # Setup itself reads the list a few times before the coordinators exist
    # (learning hosts, merging shared storage, the tracked selection); the
    # coordinators' first refreshes add exactly one between them.
    assert reads.count("cluster/resources?type=storage") == 0
    assert len(reads) <= 4, reads


async def test_a_burst_of_refreshes_reads_once(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test guests, storage and summary refreshing together share one read."""
    await _setup(hass, current_entry)
    shared_resources(hass, current_entry).forget()
    before = fake_api.paths().count("cluster/resources")
    coordinators = current_entry.runtime_data[COORDINATORS]

    await asyncio.gather(
        coordinators["qemu_101"].async_refresh(),
        coordinators["lxc_100"].async_refresh(),
        coordinators["storage_storage/pve/local"].async_refresh(),
        coordinators["proxmox_summary"].async_refresh(),
    )

    assert fake_api.paths().count("cluster/resources") == before + 1
    assert coordinators["qemu_101"].data.node == "pve"
    assert coordinators["storage_storage/pve/local"].data.disk_used is not None


async def test_the_next_burst_reads_afresh(hass: HomeAssistant) -> None:
    """Test a read older than the TTL is not served again."""
    shared = SharedResources()
    calls = 0

    def _poll(*_args: object) -> list:
        nonlocal calls
        calls += 1
        return [{"type": "node", "node": "pve"}]

    with patch("custom_components.proxmoxve.coordinator.poll_api", side_effect=_poll):
        entry = MockConfigEntry(domain="proxmoxve")
        assert await shared.get(hass, entry, object()) == [
            {"type": "node", "node": "pve"}
        ]
        assert await shared.get(hass, entry, object()) is not None
        assert calls == 1
        shared._read_at -= RESOURCES_TTL  # noqa: SLF001
        assert await shared.get(hass, entry, object()) is not None
        assert calls == 2


async def test_a_failed_read_is_shared_too(hass: HomeAssistant) -> None:
    """Test a dead host is hit once per burst, and every caller hears about it."""
    shared = SharedResources()
    calls = 0

    def _poll(*_args: object) -> list:
        nonlocal calls
        calls += 1
        msg = "host gone"
        raise UpdateFailed(msg)

    with patch("custom_components.proxmoxve.coordinator.poll_api", side_effect=_poll):
        entry = MockConfigEntry(domain="proxmoxve")
        for _ in range(3):
            with pytest.raises(UpdateFailed, match="host gone"):
                await shared.get(hass, entry, object())
    assert calls == 1


async def test_the_type_filter_is_applied_locally(hass: HomeAssistant) -> None:
    """Test `?type=storage` is a local filter over the one read."""
    shared = SharedResources()
    rows = [{"type": "node", "node": "pve"}, {"type": "storage", "storage": "local"}]
    with patch("custom_components.proxmoxve.coordinator.poll_api", return_value=rows):
        entry = MockConfigEntry(domain="proxmoxve")
        assert await shared.get(hass, entry, object(), resource_type="storage") == [
            {"type": "storage", "storage": "local"}
        ]
        assert await shared.get(hass, entry, object()) == rows
