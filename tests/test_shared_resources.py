# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""
Tests for reading `cluster/resources` once per poll burst.

Every VM, container and storage coordinator, the cluster summary and
discovery used to read the same list themselves - forty identical
requests a minute on a modest cluster. Now the first one reads and the
rest take the result, for the TTL.

The same goes for the two lists that belong to a node, its disks and its
pools: one coordinator per row, and each used to read the whole list.
"""

import asyncio
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from proxmoxer.core import ResourceException
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.proxmoxve_custom.const import (
    COORDINATORS,
    DOMAIN,
    ProxmoxType,
)
from custom_components.proxmoxve_custom.coordinator import (
    RESOURCES_TTL,
    SharedRead,
    SharedResources,
    shared_node_list,
    shared_resources,
)
from custom_components.proxmoxve_custom.issues import FORBIDDEN, RESOURCE_ISSUES

from .fake_api import NODE, FakeProxmox
from .test_setup_full import _setup

DISK_LIST = f"nodes/{NODE}/disks/list"
POOL_LIST = f"nodes/{NODE}/disks/zfs"


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

    with patch(
        "custom_components.proxmoxve_custom.coordinator.poll_api", side_effect=_poll
    ):
        entry = MockConfigEntry(domain="proxmoxve_custom")
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

    with patch(
        "custom_components.proxmoxve_custom.coordinator.poll_api", side_effect=_poll
    ):
        entry = MockConfigEntry(domain="proxmoxve_custom")
        for _ in range(3):
            with pytest.raises(UpdateFailed, match="host gone"):
                await shared.get(hass, entry, object())
    assert calls == 1


async def test_the_type_filter_is_applied_locally(hass: HomeAssistant) -> None:
    """Test `?type=storage` is a local filter over the one read."""
    shared = SharedResources()
    rows = [{"type": "node", "node": "pve"}, {"type": "storage", "storage": "local"}]
    with patch(
        "custom_components.proxmoxve_custom.coordinator.poll_api", return_value=rows
    ):
        entry = MockConfigEntry(domain="proxmoxve_custom")
        assert await shared.get(hass, entry, object(), resource_type="storage") == [
            {"type": "storage", "storage": "local"}
        ]
        assert await shared.get(hass, entry, object()) == rows


def _three_disks_two_pools(fake_api: FakeProxmox) -> None:
    """Give the node two more disks and a second pool."""
    first = fake_api.routes[DISK_LIST][0]
    for letter, serial in (("b", "S124"), ("c", "S125")):
        fake_api.routes[DISK_LIST].append(
            first
            | {
                "devpath": f"/dev/sd{letter}",
                "by_id_link": f"/dev/disk/by-id/ata-SAMSUNG_SSD_{serial}",
                "serial": serial,
                "wwn": f"0x5002538e4000000{letter}",
            }
        )
        fake_api.routes[f"nodes/{NODE}/disks/smart?disk=/dev/sd{letter}"] = (
            fake_api.routes[f"nodes/{NODE}/disks/smart?disk=/dev/sda"]
        )
    fake_api.routes[POOL_LIST].append(fake_api.routes[POOL_LIST][0] | {"name": "tank"})


async def test_setup_reads_a_nodes_disk_and_pool_list_once(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """
    Test the list setup builds the coordinators from serves their first refresh.

    Each disk read the whole list again for its one row, and Proxmox asks
    every drive for its health to make that list: four reads for three
    disks, one after the other, with Home Assistant waiting for the entry.
    """
    _three_disks_two_pools(fake_api)

    await _setup(hass, current_entry)

    coordinators = current_entry.runtime_data[COORDINATORS]
    assert len(coordinators[f"{ProxmoxType.Disk}_{NODE}"]) == 3
    assert len(coordinators[f"{ProxmoxType.ZFS}_{NODE}"]) == 2
    assert fake_api.paths().count(DISK_LIST) == 1
    assert fake_api.paths().count(POOL_LIST) == 1
    # SMART is the disk's own, and still asked per disk.
    smart = [path for path in fake_api.paths() if "/disks/smart" in path]
    assert sorted(smart) == [
        f"nodes/{NODE}/disks/smart?disk=/dev/sd{letter}" for letter in "abc"
    ]


async def test_a_burst_of_disk_refreshes_reads_the_list_once(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test the disks of a node refreshing together share one list."""
    _three_disks_two_pools(fake_api)
    await _setup(hass, current_entry)
    shared_resources(hass, current_entry).forget()
    before = fake_api.paths().count(DISK_LIST)
    disks = current_entry.runtime_data[COORDINATORS][f"{ProxmoxType.Disk}_{NODE}"]

    await asyncio.gather(*(disk.async_refresh() for disk in disks))

    assert fake_api.paths().count(DISK_LIST) == before + 1
    assert sorted(disk.data.path for disk in disks) == [
        "/dev/sda",
        "/dev/sdb",
        "/dev/sdc",
    ]


async def test_the_next_burst_reads_the_disk_list_afresh(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test a disk that fails shows up with the poll after the one that read."""
    await _setup(hass, current_entry)
    (disk,) = current_entry.runtime_data[COORDINATORS][f"{ProxmoxType.Disk}_{NODE}"]
    fake_api.routes[DISK_LIST][0]["health"] = "FAILED"

    shared_node_list(hass, current_entry, DISK_LIST)._read_at -= RESOURCES_TTL  # noqa: SLF001
    await disk.async_refresh()

    assert disk.data.health == "FAILED"


async def test_a_refused_disk_list_is_filed_for_every_disk(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test one refusal reaches each disk, and each gets its line on the repair."""
    _three_disks_two_pools(fake_api)
    await _setup(hass, current_entry)
    disks = current_entry.runtime_data[COORDINATORS][f"{ProxmoxType.Disk}_{NODE}"]
    fake_api.routes[DISK_LIST] = ResourceException(
        403, "Forbidden", "Permission check failed (/nodes/pve, Sys.Audit)"
    )
    shared_resources(hass, current_entry).forget()
    before = fake_api.paths().count(DISK_LIST)

    await asyncio.gather(*(disk.async_refresh() for disk in disks))
    await hass.async_block_till_done()

    assert fake_api.paths().count(DISK_LIST) == before + 1
    forbidden = hass.data[DOMAIN][RESOURCE_ISSUES][current_entry.entry_id][FORBIDDEN]
    assert sorted(forbidden) == sorted(
        f"{ProxmoxType.Disk}_{disk.resource_id}" for disk in disks
    )
    assert all(disk.data.path is None for disk in disks)


async def test_a_shared_read_keeps_what_it_raised_for_the_burst() -> None:
    """Test a host that is gone is asked once, and every caller hears about it."""
    shared = SharedRead()
    calls = 0

    async def _read() -> list:
        nonlocal calls
        calls += 1
        msg = "host gone"
        raise UpdateFailed(msg)

    for _ in range(3):
        with pytest.raises(UpdateFailed, match="host gone"):
            await shared.get(_read)
    assert calls == 1

    shared.forget()
    with pytest.raises(UpdateFailed, match="host gone"):
        await shared.get(_read)
    assert calls == 2


async def test_a_fresh_shared_read_asks_and_serves_those_after_it() -> None:
    """Test setup's read is made whatever is there, and is then what is there."""
    shared = SharedRead()
    answers = iter((["sda"], ["sda", "sdb"], ["never asked"]))

    async def _read() -> list:
        return next(answers)

    assert await shared.get(_read) == ["sda"]
    assert await shared.get(_read, fresh=True) == ["sda", "sdb"]
    assert await shared.get(_read) == ["sda", "sdb"]


async def test_a_cancelled_shared_read_is_not_kept() -> None:
    """
    Test a read that was cancelled leaves nothing behind for the next caller.

    Setup cancelled halfway - an entry reloaded while it waits for a slow
    node - is no answer, and must not be handed out as one.
    """
    shared = SharedRead()
    started = asyncio.Event()

    async def _hangs() -> list:
        started.set()
        await asyncio.Event().wait()
        return []

    async def _answers() -> list:
        return ["sda"]

    waiting = asyncio.create_task(shared.get(_hangs))
    await started.wait()
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting

    assert await shared.get(_answers) == ["sda"]
