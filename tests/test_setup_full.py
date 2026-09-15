# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""
Setting up against a Proxmox that answers every path.

These are the first tests that run setup with a real node name. The older
setup tests go through the version-1 migration, which loses the node, so
the node coordinators, disks, pools, buttons and the update entity were
never actually exercised there.
"""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.proxmoxve import DOMAIN
from custom_components.proxmoxve.const import (
    CONF_DISKS_ENABLE,
    CONF_LXC,
    CONF_NODES,
    CONF_QEMU,
    CONF_STORAGE,
    CONF_TASKS_ENABLE,
    COORDINATORS,
)

from .fake_api import FakeProxmox


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set the entry up and wait for the platforms."""
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


def _state(hass: HomeAssistant, entry: MockConfigEntry, unique_id: str, domain: str):  # noqa: ANN202
    """Return the state of the entity with the given unique id."""
    entity_id = er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)
    assert entity_id is not None, f"no {domain} entity with unique id {unique_id}"
    state = hass.states.get(entity_id)
    assert state is not None, f"{entity_id} has no state (disabled?)"
    return state


async def test_every_coordinator_reads_its_data(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test each coordinator ends its first refresh with data, not an error."""
    await _setup(hass, current_entry)

    coordinators = current_entry.runtime_data[COORDINATORS]
    for key, coordinator in coordinators.items():
        for single in coordinator if isinstance(coordinator, list) else [coordinator]:
            assert single.last_update_success, f"{key} failed its first refresh"
            assert single.data is not None, f"{key} has no data"

    assert set(coordinators) >= {
        "node_pve",
        "update_pve",
        "certificate_pve",
        "subscription_pve",
        "replication_pve",
        "backup_pve",
        "tasks_pve",
        "disk_pve",
        "zfs_pve",
        "qemu_101",
        "lxc_100",
        "storage_storage/pve/local",
    }
    assert len(coordinators["disk_pve"]) == 1
    assert len(coordinators["zfs_pve"]) == 1


async def test_the_node_and_its_guests_report(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test a few states the fixtures pin down, across the platforms."""
    await _setup(hass, current_entry)
    entry_id = current_entry.entry_id

    assert _state(hass, current_entry, f"{entry_id}_pve_cpu", "sensor").state == "1.35"
    assert _state(
        hass, current_entry, f"{entry_id}_pve_status", "binary_sensor"
    ).state == (STATE_ON)
    assert _state(
        hass, current_entry, f"{entry_id}_pve_status_raw", "sensor"
    ).state == ("online")
    assert _state(
        hass, current_entry, f"{entry_id}_101_status_raw", "sensor"
    ).state == ("running")
    assert _state(
        hass, current_entry, f"{entry_id}_100_status_raw", "sensor"
    ).state == ("running")
    # The VM's disk usage comes from the guest agent, not the host's zero.
    disk = _state(hass, current_entry, f"{entry_id}_101_disk_used_perc", "sensor")
    assert 36 < float(disk.state) < 37
    # The storage flags come from the node's own storage list.
    active = _state(
        hass, current_entry, f"{entry_id}_storage/pve/local_active", "binary_sensor"
    )
    assert active.state == STATE_ON


async def test_the_update_entity_reads_like_the_core_integration(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test installed and latest version come from the node and apt/update."""
    await _setup(hass, current_entry)

    state = _state(
        hass, current_entry, f"{current_entry.entry_id}_pve_node_update", "update"
    )
    assert state.state == STATE_ON
    assert state.attributes["installed_version"] == "9.0.6"
    assert state.attributes["latest_version"] == "9.0.10-p1-d1"


async def test_buttons_follow_the_permissions(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test a token without VM.Snapshot gets no snapshot button, and keeps the rest."""
    fake_api.routes["access/permissions"] = {
        "/": {"Sys.Audit": 1, "VM.Audit": 1, "Datastore.Audit": 1, "Sys.Modify": 1},
        "/vms/101": {"VM.PowerMgmt": 1},
    }
    await _setup(hass, current_entry)
    registry = er.async_get(hass)
    entry_id = current_entry.entry_id

    assert registry.async_get_entity_id("button", DOMAIN, f"{entry_id}_101_start")
    assert not registry.async_get_entity_id(
        "button", DOMAIN, f"{entry_id}_101_snapshot"
    )
    # Nothing was granted on the container at all.
    assert not registry.async_get_entity_id("button", DOMAIN, f"{entry_id}_100_start")
    # Sys.PowerMgmt on the node is missing, VM.PowerMgmt on a guest is there.
    assert not registry.async_get_entity_id("button", DOMAIN, f"{entry_id}_pve_reboot")
    assert registry.async_get_entity_id("button", DOMAIN, f"{entry_id}_pve_startall")


async def test_disks_and_pools_get_their_own_devices(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test the disk and the pool hang off the node's device."""
    await _setup(hass, current_entry)
    dev_reg = dr.async_get(hass)
    entry_id = current_entry.entry_id

    node = dev_reg.async_get_device_by_identifier(
        (DOMAIN, f"{entry_id}_NODE_pve"), entry_id
    )
    disk = dev_reg.async_get_device_by_identifier(
        (DOMAIN, f"{entry_id}_DISK_pve_0x5002538e40000001"), entry_id
    )
    # The pool device carries the data's display name, not the pool name.
    pool = dev_reg.async_get_device_by_identifier(
        (DOMAIN, f"{entry_id}_ZFS_pve_ZFS Pool rpool"), entry_id
    )

    assert node is not None
    assert disk is not None
    assert pool is not None
    assert disk.via_device_id == node.id
    assert pool.via_device_id == node.id
    assert disk.serial_number == "S123"

    temperature = _state(
        hass, current_entry, f"{entry_id}_pve_0x5002538e40000001_temperature", "sensor"
    )
    assert temperature.state == "34"
    health = _state(
        hass, current_entry, f"{entry_id}_pve_ZFS Pool rpool_health", "sensor"
    )
    assert health.state == "ONLINE"


async def test_only_the_expected_paths_are_read(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """
    Test setup does not reach for anything the fake does not know.

    The fake refuses unknown paths with a 404, which a coordinator would
    report as a failed refresh; this makes the list of paths visible when
    a new coordinator forgets to add its route.
    """
    await _setup(hass, current_entry)

    unknown = sorted({path for path in fake_api.paths() if path not in fake_api.routes})
    assert unknown == []
    assert fake_api.paths("POST") == []


async def test_deselecting_the_node_removes_its_disk_and_pool_devices(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """
    Test the options flow can drop a node that owns disks and pools.

    This used to raise AttributeError: the pool device was looked up under a
    `path` attribute that pool data does not have.
    """
    await _setup(hass, current_entry)
    dev_reg = dr.async_get(hass)
    entry_id = current_entry.entry_id
    pool = dev_reg.async_get_device_by_identifier(
        (DOMAIN, f"{entry_id}_ZFS_pve_ZFS Pool rpool"), entry_id
    )
    disk = dev_reg.async_get_device_by_identifier(
        (DOMAIN, f"{entry_id}_DISK_pve_0x5002538e40000001"), entry_id
    )
    assert pool is not None
    assert disk is not None

    result = await hass.config_entries.options.async_init(entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "change_expose"}
    )
    assert result["type"] == FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_NODES: [],
            CONF_QEMU: ["101"],
            CONF_LXC: ["100"],
            CONF_STORAGE: [],
            CONF_DISKS_ENABLE: True,
            CONF_TASKS_ENABLE: True,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "changes_successful"
    assert dev_reg.async_get(pool.id) is None
    assert dev_reg.async_get(disk.id) is None
