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


def _discovery_coordinator(
    hass: HomeAssistant, entry: MockConfigEntry
) -> tuple[ProxmoxDiscoveryCoordinator, AsyncMock, AsyncMock]:
    """
    Build a discovery coordinator over a real entry, with mocked add/remove.

    Constructing the real thing would register it with the entry's lifecycle;
    the update method only needs these attributes.
    """
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


async def test_a_discovered_guest_is_wired_up_without_a_reload(
    hass: HomeAssistant,
) -> None:
    """
    Test the add path builds coordinators and hands the guest to every platform.

    The shared mock cannot answer a guest's status, so no entity comes out
    of it here; what this pins down is the wiring - a coordinator appears,
    each platform's callback is asked, and nothing is reloaded.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        data={**USER_INPUT_OK, CONF_TOKEN_NAME: "", CONF_STORAGE: []},
        options={CONF_AUTO_DISCOVERY: True, CONF_DISKS_ENABLE: False},
        version=7,
    )

    with (
        patch("proxmoxer.ProxmoxResource.get", return_value=MOCK_GET_RESPONSE),
        NO_AUTH_CALL,
    ):
        await async_init_integration(hass, entry)
        coordinators = entry.runtime_data["coordinators"]
        discovery = coordinators[f"{ProxmoxType.Proxmox}_discovery"]
        callbacks = entry.runtime_data["resource_callbacks"]
        # sensor, binary_sensor, button and update each registered one.
        assert len(callbacks) == 4

        # Pretend guest 1001 had not been tracked, then let discovery add it.
        await discovery._remove_resource(ProxmoxType.QEMU, "1001")  # noqa: SLF001
        assert f"{ProxmoxType.QEMU}_1001" not in coordinators

        with (
            patch.object(hass.config_entries, "async_schedule_reload") as reload,
            patch(
                "custom_components.proxmoxve.update.async_setup_updates",
                return_value=[],
            ) as update_builder,
        ):
            await discovery._add_resource(ProxmoxType.QEMU, "1001")  # noqa: SLF001

    assert f"{ProxmoxType.QEMU}_1001" in coordinators
    reload.assert_not_called()
    # The update platform only builds for nodes; it was asked and declined.
    update_builder.assert_not_called()


async def test_removing_a_node_drops_everything_it_owned(hass: HomeAssistant) -> None:
    """Test a vanished node takes its update, backup and task coordinators along."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        data={**USER_INPUT_OK, CONF_TOKEN_NAME: "", CONF_STORAGE: []},
        options={CONF_AUTO_DISCOVERY: True, CONF_DISKS_ENABLE: False},
        version=7,
    )

    with (
        patch("proxmoxer.ProxmoxResource.get", return_value=MOCK_GET_RESPONSE),
        NO_AUTH_CALL,
    ):
        await async_init_integration(hass, entry)
        coordinators = entry.runtime_data["coordinators"]
        discovery = coordinators[f"{ProxmoxType.Proxmox}_discovery"]
        owned_before = [key for key in coordinators if key.endswith("_pve")]
        assert f"{ProxmoxType.Node}_pve" in owned_before
        assert f"{ProxmoxType.Backup}_pve" in owned_before

        await discovery._remove_resource(ProxmoxType.Node, "pve")  # noqa: SLF001

    assert not [key for key in coordinators if key.endswith("_pve")]
