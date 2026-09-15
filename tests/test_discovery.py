# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for following the cluster's resource list automatically."""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.proxmoxve import DOMAIN
from custom_components.proxmoxve.const import (
    CONF_AUTO_DISCOVERY,
    CONF_DISKS_ENABLE,
    CONF_LXC,
    CONF_NODES,
    CONF_QEMU,
    CONF_STORAGE,
    CONF_TOKEN_NAME,
    ProxmoxType,
)
from custom_components.proxmoxve.coordinator import ProxmoxDiscoveryCoordinator
from custom_components.proxmoxve.discovery import (
    apply_discovery,
    discovered_resources,
    tracked_resources,
)

from . import async_init_integration
from .const import MOCK_GET_RESPONSE, USER_INPUT_OK

NO_AUTH_CALL = patch(
    "proxmoxer.backends.https.ProxmoxHTTPAuth._get_new_tokens",
    return_value=None,
)

EVERYTHING = {
    CONF_NODES: ["pve"],
    CONF_QEMU: ["101", "1001"],
    CONF_LXC: ["100", "1000"],
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


async def test_apply_discovery_when_nothing_changed(hass: HomeAssistant) -> None:
    """Test an identical listing changes nothing and says so."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={**USER_INPUT_OK, **EVERYTHING}, options={}
    )
    entry.add_to_hass(hass)

    assert apply_discovery(hass, entry, EVERYTHING) is False
    assert tracked_resources(entry) == EVERYTHING


async def test_apply_discovery_picks_up_new_guests(hass: HomeAssistant) -> None:
    """Test a guest the entry did not track is added to it."""
    entry = MockConfigEntry(domain=DOMAIN, data=USER_INPUT_OK, options={})
    entry.add_to_hass(hass)

    assert apply_discovery(hass, entry, EVERYTHING) is True
    assert tracked_resources(entry) == EVERYTHING
    # The rest of the entry is untouched.
    assert entry.data["host"] == USER_INPUT_OK["host"]


async def test_apply_discovery_drops_a_vanished_guest(hass: HomeAssistant) -> None:
    """Test a guest the cluster no longer lists loses its device."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={**USER_INPUT_OK, **EVERYTHING}, options={}
    )
    entry.add_to_hass(hass)
    dev_reg = dr.async_get(hass)
    gone = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"{entry.entry_id}_{ProxmoxType.QEMU.upper()}_1001")},
    )
    kept = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"{entry.entry_id}_{ProxmoxType.QEMU.upper()}_101")},
    )

    listing = {**EVERYTHING, CONF_QEMU: ["101"]}
    assert apply_discovery(hass, entry, listing) is True

    assert tracked_resources(entry)[CONF_QEMU] == ["101"]
    assert dev_reg.async_get(gone.id) is None
    assert dev_reg.async_get(kept.id) is not None


async def test_a_vanished_node_takes_its_disks_along(hass: HomeAssistant) -> None:
    """Test the disk and pool devices under a removed node go with it."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={**USER_INPUT_OK, **EVERYTHING, CONF_NODES: ["pve", "pve2"]},
        options={},
    )
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
        )
    ]

    assert apply_discovery(hass, entry, EVERYTHING) is True

    assert [dev_reg.async_get(device.id) is not None for device in devices] == [
        False,
        False,
        False,
        True,
        True,
    ]


async def test_coordinator_reloads_on_a_change() -> None:
    """Test a changed listing brings the entry in line and schedules a reload."""
    coordinator = object.__new__(ProxmoxDiscoveryCoordinator)
    coordinator.hass = MagicMock()
    coordinator.hass.async_add_executor_job = AsyncMock(
        side_effect=lambda func, *args: func(*args)
    )
    coordinator.config_entry = MagicMock()
    coordinator.proxmox = MagicMock()
    coordinator.resource_id = "discovery"

    with (
        patch(
            "custom_components.proxmoxve.coordinator.poll_api",
            return_value=MOCK_GET_RESPONSE,
        ),
        patch(
            "custom_components.proxmoxve.coordinator.apply_discovery",
            return_value=True,
        ) as apply,
    ):
        found = await coordinator._async_update_data()  # noqa: SLF001

    assert found == EVERYTHING
    apply.assert_called_once_with(
        coordinator.hass, coordinator.config_entry, EVERYTHING
    )
    coordinator.hass.config_entries.async_schedule_reload.assert_called_once_with(
        coordinator.config_entry.entry_id
    )


async def test_coordinator_stays_quiet_without_a_change() -> None:
    """Test an unchanged listing does not reload anything."""
    coordinator = object.__new__(ProxmoxDiscoveryCoordinator)
    coordinator.hass = MagicMock()
    coordinator.hass.async_add_executor_job = AsyncMock(
        side_effect=lambda func, *args: func(*args)
    )
    coordinator.config_entry = MagicMock()
    coordinator.proxmox = MagicMock()
    coordinator.resource_id = "discovery"

    with (
        patch(
            "custom_components.proxmoxve.coordinator.poll_api",
            return_value=MOCK_GET_RESPONSE,
        ),
        patch(
            "custom_components.proxmoxve.coordinator.apply_discovery",
            return_value=False,
        ),
    ):
        await coordinator._async_update_data()  # noqa: SLF001

    coordinator.hass.config_entries.async_schedule_reload.assert_not_called()


async def test_setup_with_discovery_tracks_everything(hass: HomeAssistant) -> None:
    """Test switching the option on makes setup track what the cluster lists."""
    # The current entry version: the migrations of older ones reset the
    # options, which would switch discovery off again before setup.
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        data={**USER_INPUT_OK, CONF_TOKEN_NAME: "", CONF_STORAGE: []},
        # The shared mock answers every path with the guest list, which the
        # disk lookup cannot make sense of; disks are not what is under test.
        options={CONF_AUTO_DISCOVERY: True, CONF_DISKS_ENABLE: False},
        version=7,
    )

    with (
        patch("proxmoxer.ProxmoxResource.get", return_value=MOCK_GET_RESPONSE),
        NO_AUTH_CALL,
    ):
        await async_init_integration(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    assert tracked_resources(entry) == EVERYTHING
    assert f"{ProxmoxType.Proxmox}_discovery" in entry.runtime_data["coordinators"]


async def test_setup_without_discovery_leaves_the_selection(
    hass: HomeAssistant,
) -> None:
    """Test the default keeps tracking exactly what was picked."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        data={**USER_INPUT_OK, CONF_TOKEN_NAME: "", CONF_STORAGE: []},
        options={CONF_DISKS_ENABLE: False},
        version=7,
    )

    with (
        patch("proxmoxer.ProxmoxResource.get", return_value=MOCK_GET_RESPONSE),
        NO_AUTH_CALL,
    ):
        await async_init_integration(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    assert tracked_resources(entry)[CONF_QEMU] == ["101"]
    assert f"{ProxmoxType.Proxmox}_discovery" not in entry.runtime_data["coordinators"]
