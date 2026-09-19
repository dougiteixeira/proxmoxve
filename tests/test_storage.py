# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for a storage's flags, and for the ZFS pool coordinator."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import EntityCategory
from homeassistant.helpers.typing import UNDEFINED
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.proxmoxve.binary_sensor import (
    PROXMOX_BINARYSENSOR_STORAGE,
    ProxmoxBinarySensorEntity,
)
from custom_components.proxmoxve.coordinator import (
    ProxmoxStorageCoordinator,
    ProxmoxZFSCoordinator,
    _flag_or_undefined,
)
from custom_components.proxmoxve.models import ProxmoxStorageData

# The storage as the cluster's resource list (`GET /cluster/resources`) lists it.
CLUSTER_VIEW = [
    {
        "id": "storage/pve1/nas",
        "storage": "nas",
        "node": "pve1",
        "type": "storage",
        "plugintype": "nfs",
        "status": "available",
        "content": "backup,iso",
        "disk": 1_000_000,
        "maxdisk": 4_000_000,
        "shared": 1,
    }
]

# The same storage as `GET /nodes/pve1/storage?storage=nas` reports it,
# which is the only place `active` and `enabled` appear.
NODE_VIEW = [
    {
        "storage": "nas",
        "type": "nfs",
        "content": "backup,iso",
        "active": 1,
        "enabled": 1,
        "shared": 1,
        "avail": 3_000_000,
        "used": 1_000_000,
        "total": 4_000_000,
        "used_fraction": 0.25,
    }
]


def _storage_coordinator(responses: dict[str, object]) -> ProxmoxStorageCoordinator:
    """
    Build a storage coordinator whose API answers come from `responses`.

    Constructing the real thing would need a config entry and an event
    loop; the update method only touches these attributes.
    """
    coordinator = object.__new__(ProxmoxStorageCoordinator)
    coordinator.hass = MagicMock()
    coordinator.hass.async_add_executor_job = AsyncMock(
        side_effect=lambda func, *args: func(*args)
    )
    # The shared resource read keeps its cache in hass.data, per entry.
    coordinator.hass.data = {}
    coordinator.config_entry = MagicMock()
    coordinator.config_entry.entry_id = "test"
    coordinator.proxmox = MagicMock()
    coordinator.resource_id = "storage/pve1/nas"

    def _poll(
        _hass: object,
        _entry: object,
        _proxmox: object,
        api_path: str,
        _category: object,
        _resource_id: object,
    ) -> object:
        return responses.get(api_path)

    coordinator._poll = _poll  # noqa: SLF001
    return coordinator


async def _update(responses: dict[str, object]) -> ProxmoxStorageData:
    """Run one coordinator update against the given API answers."""
    coordinator = _storage_coordinator(responses)
    with patch(
        "custom_components.proxmoxve.coordinator.poll_api",
        side_effect=coordinator._poll,  # noqa: SLF001
    ):
        return await coordinator._async_update_data()  # noqa: SLF001


def _binary_sensor(key: str, data: SimpleNamespace) -> ProxmoxBinarySensorEntity:
    """Build a storage binary sensor over the given data."""
    coordinator = MagicMock()
    coordinator.data = data
    description = next(d for d in PROXMOX_BINARYSENSOR_STORAGE if d.key == key)
    return ProxmoxBinarySensorEntity(
        coordinator=coordinator,
        unique_id=f"test_{key}",
        info_device={},
        description=description,
    )


def test_a_flag_that_is_absent_stays_unknown() -> None:
    """Test a missing flag is not mistaken for one that is off."""
    assert _flag_or_undefined(None) is UNDEFINED
    assert _flag_or_undefined(0) is False
    assert _flag_or_undefined(1) is True


async def test_the_node_view_is_read() -> None:
    """Test the flags come from the node's storage list."""
    data = await _update(
        {
            "cluster/resources": CLUSTER_VIEW,
            "nodes/pve1/storage?storage=nas": NODE_VIEW,
        }
    )

    assert data.node == "pve1"
    assert data.active is True
    assert data.enabled is True
    assert data.shared is True
    # What the sensors already reported is untouched.
    assert data.disk_used == 1_000_000
    assert data.disk_total == 4_000_000


async def test_an_unreachable_storage_reads_inactive() -> None:
    """Test a storage the node cannot reach is off, not unknown."""
    node_view = [{**NODE_VIEW[0], "active": 0}]
    data = await _update(
        {
            "cluster/resources": CLUSTER_VIEW,
            "nodes/pve1/storage?storage=nas": node_view,
        }
    )

    assert data.active is False
    assert data.enabled is True


async def test_without_the_node_view_the_flags_are_unknown() -> None:
    """
    Test a node list that could not be read leaves the flags undefined.

    That is how the platform knows not to create the entities, rather than
    creating three that can only ever say "off".
    """
    data = await _update(
        {
            "cluster/resources": CLUSTER_VIEW,
            "nodes/pve1/storage?storage=nas": None,
        }
    )

    assert data.active is UNDEFINED
    assert data.enabled is UNDEFINED
    assert data.shared is UNDEFINED


def test_binary_sensors_follow_the_flags() -> None:
    """Test each flag drives its own binary sensor."""
    data = SimpleNamespace(active=True, enabled=False, shared=True)

    assert _binary_sensor("active", data).is_on is True
    assert _binary_sensor("enabled", data).is_on is False
    assert _binary_sensor("shared", data).is_on is True


def test_defaults_match_the_core_integration() -> None:
    """Test all three are diagnostic and on, as in the core integration."""
    for description in PROXMOX_BINARYSENSOR_STORAGE:
        assert description.entity_registry_enabled_default is True
        assert description.entity_category is EntityCategory.DIAGNOSTIC


POOLS = [
    {"name": "rpool", "health": "ONLINE", "size": 1, "alloc": 1, "free": 0},
    {"name": "hddpool", "health": "DEGRADED", "size": 2, "alloc": 1, "free": 1},
]


def _zfs_coordinator(answer: object) -> ProxmoxZFSCoordinator:
    """
    Build a ZFS coordinator whose one read returns `answer`.

    Constructing the real thing would need a config entry and an event
    loop; the update method only touches these attributes.
    """
    coordinator = object.__new__(ProxmoxZFSCoordinator)
    coordinator.hass = MagicMock()
    coordinator.hass.async_add_executor_job = _returning(answer)
    coordinator.config_entry = MagicMock()
    coordinator.node_name = "pve"
    coordinator.resource_id = "rpool"
    coordinator._proxmox = MagicMock()  # noqa: SLF001
    return coordinator


def _returning(answer: object):  # noqa: ANN202 - a stand-in for the executor
    """Return an executor stand-in that answers with `answer`."""

    async def _run(*_args: object, **_kwargs: object) -> object:
        return answer

    return _run


async def test_a_refused_pool_read_fails_the_update() -> None:
    """
    Test a refused read is one line, not a traceback every minute.

    `poll_api` hands back nothing for a 403 - it files the repair instead -
    and iterating that raised `TypeError: 'NoneType' object is not iterable`.
    """
    coordinator = _zfs_coordinator(None)

    with pytest.raises(UpdateFailed, match="not available"):
        await coordinator._async_update_data()  # noqa: SLF001


async def test_a_pool_that_is_gone_fails_the_update() -> None:
    """
    Test the guard for a pool the listing no longer has actually fires.

    It was written against `pool_status is None` while the variable started
    as `[]`, so it never ran and `.get` was called on a list instead.
    """
    coordinator = _zfs_coordinator([{"name": "hddpool"}])

    with pytest.raises(UpdateFailed, match="unable to be found"):
        await coordinator._async_update_data()  # noqa: SLF001


async def test_an_answer_that_is_not_a_listing_fails_the_update() -> None:
    """Test anything but pools is reported, rather than iterated into pieces."""
    coordinator = _zfs_coordinator({"name": "rpool"})

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()  # noqa: SLF001


async def test_the_pool_is_read_as_before() -> None:
    """Test the working case is untouched: the named pool's figures."""
    coordinator = _zfs_coordinator(POOLS)

    data = await coordinator._async_update_data()  # noqa: SLF001

    assert data.name == "ZFS Pool rpool"
    assert data.health == "ONLINE"
    assert data.node == "pve"


async def test_an_entry_without_a_name_is_skipped() -> None:
    """Test a listing entry the API hands back without a name does not raise."""
    coordinator = _zfs_coordinator([{"health": "ONLINE"}, *POOLS])

    data = await coordinator._async_update_data()  # noqa: SLF001

    assert data.health == "ONLINE"
