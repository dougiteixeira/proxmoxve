# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for a storage's active, enabled and shared flags."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.helpers.typing import UNDEFINED

from custom_components.proxmoxve.binary_sensor import (
    PROXMOX_BINARYSENSOR_STORAGE,
    ProxmoxBinarySensorEntity,
)
from custom_components.proxmoxve.coordinator import (
    ProxmoxStorageCoordinator,
    _flag_or_undefined,
)
from custom_components.proxmoxve.models import ProxmoxStorageData

# The storage as `GET /cluster/resources?type=storage` lists it.
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


def _coordinator(responses: dict[str, object]) -> ProxmoxStorageCoordinator:
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
    coordinator.config_entry = MagicMock()
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
    coordinator = _coordinator(responses)
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
            "cluster/resources?type=storage": CLUSTER_VIEW,
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
            "cluster/resources?type=storage": CLUSTER_VIEW,
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
            "cluster/resources?type=storage": CLUSTER_VIEW,
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


def test_only_active_is_on_by_default() -> None:
    """
    Test the configuration flags stay off until asked for.

    `enabled` and `shared` change when someone edits the storage; only
    `active` changes on its own.
    """
    defaults = {
        d.key: d.entity_registry_enabled_default for d in PROXMOX_BINARYSENSOR_STORAGE
    }

    assert defaults == {"active": True, "enabled": False, "shared": False}
