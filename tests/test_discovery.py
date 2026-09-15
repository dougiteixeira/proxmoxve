# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for following the cluster's resource list automatically."""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.proxmoxve import DOMAIN
from custom_components.proxmoxve.const import (
    CONF_AUTO_DISCOVERY,
    CONF_LXC,
    CONF_NODES,
    CONF_QEMU,
    CONF_STORAGE,
    COORDINATORS,
    TRACKED,
    ProxmoxType,
)
from custom_components.proxmoxve.coordinator import ProxmoxDiscoveryCoordinator
from custom_components.proxmoxve.discovery import (
    discovered_resources,
    remember_resources,
    remove_stale_devices,
    selected_resources,
    tracked_resources,
)

from .const import MOCK_GET_RESPONSE, USER_INPUT_OK
from .fake_api import FakeProxmox, add_guest, remove_guest

# What the flat mock's guest list amounts to ...
EVERYTHING = {
    CONF_NODES: ["pve"],
    CONF_QEMU: ["101", "1001"],
    CONF_LXC: ["100", "1000"],
    CONF_STORAGE: ["storage/pve/ext", "storage/pve/local"],
}
# ... and what the path-aware fake's cluster lists.
FAKE_EVERYTHING = {
    CONF_NODES: ["pve"],
    CONF_QEMU: ["101"],
    CONF_LXC: ["100"],
    CONF_STORAGE: ["storage/pve/ext", "storage/pve/local"],
}


def test_discovered_resources_reads_the_listing() -> None:
    """Test nodes, guests and storages are picked out, and SDN is not."""
    assert discovered_resources(MOCK_GET_RESPONSE) == EVERYTHING


def test_templates_are_never_tracked() -> None:
    """Test a template is left out: it never runs, so nothing on it could change."""
    listing = [*MOCK_GET_RESPONSE, {"type": "qemu", "vmid": 9000, "template": 1}]

    assert discovered_resources(listing)[CONF_QEMU] == ["101", "1001"]


def test_guests_are_sorted_numerically() -> None:
    """Test 1001 comes after 101, not before it."""
    assert discovered_resources(MOCK_GET_RESPONSE)[CONF_QEMU] == ["101", "1001"]


def test_tracked_falls_back_to_the_selection() -> None:
    """Test what is tracked is the selection until setup has decided otherwise."""
    entry = MockConfigEntry(domain=DOMAIN, data=USER_INPUT_OK)

    assert tracked_resources(entry) == selected_resources(entry)
    assert tracked_resources(entry)[CONF_QEMU] == ["101"]


async def test_remember_resources_leaves_the_selection_alone(
    hass: HomeAssistant,
) -> None:
    """
    Test discovery changes what is tracked, never what was picked.

    That is what lets the old selection come back untouched when discovery
    is switched off again.
    """
    entry = MockConfigEntry(domain=DOMAIN, data=USER_INPUT_OK)
    entry.add_to_hass(hass)
    entry.runtime_data = {TRACKED: selected_resources(entry)}

    remember_resources(entry, EVERYTHING)

    assert tracked_resources(entry) == EVERYTHING
    assert selected_resources(entry)[CONF_QEMU] == ["101"]
    assert entry.data[CONF_QEMU] == ["101"]


async def test_stale_devices_are_removed_at_setup(hass: HomeAssistant) -> None:
    """Test devices of guests the cluster no longer lists are detached."""
    entry = MockConfigEntry(domain=DOMAIN, data=USER_INPUT_OK, options={})
    entry.add_to_hass(hass)
    dev_reg = dr.async_get(hass)
    gone = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"{entry.entry_id}_{ProxmoxType.QEMU.upper()}_4711")},
    )
    kept = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"{entry.entry_id}_{ProxmoxType.QEMU.upper()}_101")},
    )
    cluster = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"{entry.entry_id}_cluster")},
    )

    remove_stale_devices(hass, entry, EVERYTHING)

    assert dev_reg.async_get(gone.id) is None
    assert dev_reg.async_get(kept.id) is not None
    assert dev_reg.async_get(cluster.id) is not None


async def test_a_vanished_node_takes_its_disks_along(hass: HomeAssistant) -> None:
    """Test the disk and pool devices under a removed node go with it."""
    entry = MockConfigEntry(domain=DOMAIN, data=USER_INPUT_OK, options={})
    entry.add_to_hass(hass)
    dev_reg = dr.async_get(hass)
    devices = [
        dev_reg.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, f"{entry.entry_id}_{identifier}")},
        )
        for identifier in (
            "NODE_pve2",
            "DISK_pve2_ata-SOMEDISK",
            "ZFS_pve2_rpool",
            # Same prefix as a name, different node: must survive.
            "NODE_pve",
            "DISK_pve_ata-OTHERDISK",
            "STORAGE_pve/local",
        )
    ]

    remove_stale_devices(hass, entry, EVERYTHING)

    assert [dev_reg.async_get(device.id) is not None for device in devices] == [
        False,
        False,
        False,
        True,
        True,
        True,
    ]


def _discovery_coordinator(
    hass: HomeAssistant, entry: MockConfigEntry
) -> tuple[ProxmoxDiscoveryCoordinator, AsyncMock, AsyncMock]:
    """
    Build a discovery coordinator over a real entry, with mocked add/remove.

    Constructing the real thing would register it with the entry's lifecycle;
    the update method only needs these attributes.
    """
    entry.runtime_data = {TRACKED: selected_resources(entry)}
    coordinator = object.__new__(ProxmoxDiscoveryCoordinator)
    coordinator.hass = hass
    coordinator.config_entry = entry
    coordinator.proxmox = MagicMock()
    coordinator.resource_id = "discovery"
    add = AsyncMock()
    remove = AsyncMock()
    coordinator._add_resource = add  # noqa: SLF001
    coordinator._remove_resource = remove  # noqa: SLF001
    return coordinator, add, remove


async def test_coordinator_adds_what_is_new(hass: HomeAssistant) -> None:
    """Test a guest the cluster gained is set up on the spot - nodes first."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={**USER_INPUT_OK, **EVERYTHING, CONF_QEMU: ["101"], CONF_NODES: []},
    )
    entry.add_to_hass(hass)
    coordinator, add, remove = _discovery_coordinator(hass, entry)

    with patch(
        "custom_components.proxmoxve.coordinator.poll_api",
        return_value=MOCK_GET_RESPONSE,
    ):
        found = await coordinator._async_update_data()  # noqa: SLF001

    assert found == EVERYTHING
    assert tracked_resources(entry) == EVERYTHING
    # The selection in the entry is not what discovery writes to.
    assert entry.data[CONF_QEMU] == ["101"]
    assert [call.args for call in add.await_args_list] == [
        (ProxmoxType.Node, "pve"),
        (ProxmoxType.QEMU, "1001"),
    ]
    remove.assert_not_awaited()


async def test_coordinator_removes_what_is_gone(hass: HomeAssistant) -> None:
    """Test a guest the cluster lost is stopped and loses its device."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={**USER_INPUT_OK, **EVERYTHING, CONF_LXC: ["100", "1000", "2000"]},
    )
    entry.add_to_hass(hass)
    dev_reg = dr.async_get(hass)
    gone = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"{entry.entry_id}_{ProxmoxType.LXC.upper()}_2000")},
    )
    coordinator, add, remove = _discovery_coordinator(hass, entry)

    with patch(
        "custom_components.proxmoxve.coordinator.poll_api",
        return_value=MOCK_GET_RESPONSE,
    ):
        await coordinator._async_update_data()  # noqa: SLF001

    assert tracked_resources(entry) == EVERYTHING
    remove.assert_awaited_once_with(ProxmoxType.LXC, "2000")
    assert dev_reg.async_get(gone.id) is None
    add.assert_not_awaited()


async def test_coordinator_stays_quiet_without_a_change(hass: HomeAssistant) -> None:
    """Test an unchanged listing touches nothing."""
    entry = MockConfigEntry(domain=DOMAIN, data={**USER_INPUT_OK, **EVERYTHING})
    entry.add_to_hass(hass)
    coordinator, add, remove = _discovery_coordinator(hass, entry)

    with patch(
        "custom_components.proxmoxve.coordinator.poll_api",
        return_value=MOCK_GET_RESPONSE,
    ):
        await coordinator._async_update_data()  # noqa: SLF001

    add.assert_not_awaited()
    remove.assert_not_awaited()


async def test_setup_with_discovery_tracks_everything(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test switching the option on makes setup track what the cluster lists."""
    hass.config_entries.async_update_entry(
        current_entry, options={CONF_AUTO_DISCOVERY: True}
    )

    await hass.config_entries.async_setup(current_entry.entry_id)
    await hass.async_block_till_done()

    assert current_entry.state is ConfigEntryState.LOADED
    assert tracked_resources(current_entry) == FAKE_EVERYTHING
    # ... while the picked selection in the entry stays exactly as it was.
    assert current_entry.data[CONF_STORAGE] == ["storage/pve/local"]
    assert (
        f"{ProxmoxType.Proxmox}_discovery" in current_entry.runtime_data[COORDINATORS]
    )


async def test_setup_without_discovery_leaves_the_selection(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test the default keeps tracking exactly what was picked."""
    await hass.config_entries.async_setup(current_entry.entry_id)
    await hass.async_block_till_done()

    assert current_entry.state is ConfigEntryState.LOADED
    assert tracked_resources(current_entry)[CONF_STORAGE] == ["storage/pve/local"]
    assert (
        f"{ProxmoxType.Proxmox}_discovery"
        not in (current_entry.runtime_data[COORDINATORS])
    )


async def test_a_new_guest_gets_its_entities_without_a_reload(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """
    Test the whole way: a VM appears in the cluster, its entities appear here.

    Nothing is reloaded; the discovery coordinator builds the coordinators
    and asks every platform for the entities of that one guest.
    """
    hass.config_entries.async_update_entry(
        current_entry, options={CONF_AUTO_DISCOVERY: True}
    )
    await hass.config_entries.async_setup(current_entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    entry_id = current_entry.entry_id
    assert (
        registry.async_get_entity_id("sensor", DOMAIN, f"{entry_id}_1001_status_raw")
        is None
    )

    add_guest(fake_api.routes, "qemu", 1001, "vm-new")
    discovery = current_entry.runtime_data[COORDINATORS][
        f"{ProxmoxType.Proxmox}_discovery"
    ]
    with (
        patch.object(hass.config_entries, "async_schedule_reload") as schedule_reload,
        patch.object(hass.config_entries, "async_reload") as reload,
    ):
        await discovery.async_refresh()
        await hass.async_block_till_done()

    schedule_reload.assert_not_called()
    reload.assert_not_called()
    status_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry_id}_1001_status_raw"
    )
    assert status_id is not None
    assert hass.states.get(status_id).state == "running"
    assert registry.async_get_entity_id("button", DOMAIN, f"{entry_id}_1001_start")
    assert registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{entry_id}_1001_status"
    )
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{entry_id}_QEMU_1001"), entry_id
    )
    assert device is not None
    assert tracked_resources(current_entry)[CONF_QEMU] == ["101", "1001"]


async def test_a_vanished_guest_loses_its_entities(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test a VM deleted in the cluster disappears here, device and all."""
    hass.config_entries.async_update_entry(
        current_entry, options={CONF_AUTO_DISCOVERY: True}
    )
    await hass.config_entries.async_setup(current_entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    entry_id = current_entry.entry_id
    device = dev_reg.async_get_device_by_identifier(
        (DOMAIN, f"{entry_id}_QEMU_101"), entry_id
    )
    assert device is not None
    assert registry.async_get_entity_id("sensor", DOMAIN, f"{entry_id}_101_status_raw")

    remove_guest(fake_api.routes, "qemu", 101)
    discovery = current_entry.runtime_data[COORDINATORS][
        f"{ProxmoxType.Proxmox}_discovery"
    ]
    await discovery.async_refresh()
    await hass.async_block_till_done()

    assert dev_reg.async_get(device.id) is None
    assert (
        registry.async_get_entity_id("sensor", DOMAIN, f"{entry_id}_101_status_raw")
        is None
    )
    assert f"{ProxmoxType.QEMU}_101" not in current_entry.runtime_data[COORDINATORS]
    assert tracked_resources(current_entry)[CONF_QEMU] == []
    # The selection in the entry is not what discovery writes to.
    assert current_entry.data[CONF_QEMU] == ["101"]


async def test_a_guest_only_the_cluster_knows_gets_its_entities_at_setup(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """
    Test a container nobody picked, but the cluster lists, is set up in full.

    With discovery on, setup tracked it and built its coordinator - but the
    platforms read the picked selection, so the container never got its
    entities. What was left was a bare device the coordinator had created
    to link it to its node: named after the config entry, no model, empty.
    """
    add_guest(fake_api.routes, "lxc", 9999, "test")
    hass.config_entries.async_update_entry(
        current_entry, options={CONF_AUTO_DISCOVERY: True}
    )
    await hass.config_entries.async_setup(current_entry.entry_id)
    await hass.async_block_till_done()

    entry_id = current_entry.entry_id
    registry = er.async_get(hass)
    status_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry_id}_9999_status_raw"
    )
    assert status_id is not None
    assert hass.states.get(status_id).state == "running"
    assert registry.async_get_entity_id("button", DOMAIN, f"{entry_id}_9999_stop")
    assert registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{entry_id}_9999_status"
    )
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{entry_id}_LXC_9999"), entry_id
    )
    assert device is not None
    assert device.name == "LXC test (9999)"
    assert device.model == "LXC"
    assert device.name != current_entry.title
    # The storage the fake lists but the entry never picked, likewise.
    assert registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry_id}_storage/pve/ext_node"
    )
