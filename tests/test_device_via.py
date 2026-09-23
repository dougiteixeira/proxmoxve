# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for how a device is linked to the node it lives on."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.proxmoxve import DOMAIN, device_info
from custom_components.proxmoxve.const import COORDINATORS, ProxmoxType

from .fake_api import NODE, FakeProxmox


async def _setup(
    hass: HomeAssistant, fake_api: FakeProxmox, entry: MockConfigEntry
) -> MockConfigEntry:
    """Set up the integration against the fake API and return its entry."""
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_links_to_a_node_that_has_a_device(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test the parent id is filled in for a node that does have a device."""
    entry = await _setup(hass, fake_api, current_entry)
    node_identifier = (DOMAIN, f"{entry.entry_id}_{ProxmoxType.Node.upper()}_pve")
    # Setup created the node device; this is the same one.
    node = dr.async_get(hass).async_get_device_by_identifier(
        node_identifier, entry.entry_id
    )
    assert node is not None

    info = device_info(
        hass=hass,
        config_entry=entry,
        api_category=ProxmoxType.ZFS,
        node="pve",
        resource_id="tank",
    )

    assert info["via_device_id"] == node.id
    assert "via_device" not in info


async def test_link_is_dropped_for_a_node_without_a_device(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """
    Test no link is claimed to a node that has no device.

    Home Assistant reported a device created naming a parent that does not
    exist, and drops the link regardless. This happens for anything sitting on
    a node the user did not select. Leaving the link out loses nothing and
    keeps that report out of the log.
    """
    entry = await _setup(hass, fake_api, current_entry)

    info = device_info(
        hass=hass,
        config_entry=entry,
        api_category=ProxmoxType.ZFS,
        node="a-node-nobody-selected",
        resource_id="tank",
    )

    assert info["via_device_id"] is None


async def test_a_refresh_does_not_invent_a_guest_device(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """
    Test linking a guest to its node creates no device that is not there.

    The guest coordinator refreshes before the platforms create the device,
    and used to create it itself - bare, and named after the config entry.
    Whenever no platform came along to fill it in, that is what stayed.
    """
    entry = await _setup(hass, fake_api, current_entry)
    dev_reg = dr.async_get(hass)
    identifier = (DOMAIN, f"{entry.entry_id}_{ProxmoxType.LXC.upper()}_100")
    device = dev_reg.async_get_device_by_identifier(identifier, entry.entry_id)
    assert device is not None
    dev_reg.async_remove_device(device.id)

    coordinator = entry.runtime_data[COORDINATORS][f"{ProxmoxType.LXC}_100"]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert dev_reg.async_get_device_by_identifier(identifier, entry.entry_id) is None


async def test_a_guest_renamed_in_proxmox_is_renamed_here(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """
    Test the device follows a rename, instead of keeping the old name.

    A guest renamed in Proxmox keeps its id, so it stays the same device -
    and the name was only ever written when the device was created, which
    left a container created and then named showing its id forever.
    """
    entry = await _setup(hass, fake_api, current_entry)
    dev_reg = dr.async_get(hass)
    identifier = (DOMAIN, f"{entry.entry_id}_{ProxmoxType.LXC.upper()}_100")
    device = dev_reg.async_get_device_by_identifier(identifier, entry.entry_id)
    assert device is not None
    assert device.name == "LXC lxc-test-100 (100)"

    fake_api.routes[f"nodes/{NODE}/lxc/100/status/current"]["name"] = "qv-test"
    coordinator = entry.runtime_data[COORDINATORS][f"{ProxmoxType.LXC}_100"]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    device = dev_reg.async_get_device_by_identifier(identifier, entry.entry_id)
    assert device is not None
    assert device.name == "LXC qv-test (100)"


async def test_a_name_given_here_survives_a_rename(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test a name set in Home Assistant is what is shown, rename or not."""
    entry = await _setup(hass, fake_api, current_entry)
    dev_reg = dr.async_get(hass)
    identifier = (DOMAIN, f"{entry.entry_id}_{ProxmoxType.QEMU.upper()}_101")
    device = dev_reg.async_get_device_by_identifier(identifier, entry.entry_id)
    assert device is not None
    dev_reg.async_update_device(device.id, name_by_user="The one in the cellar")

    fake_api.routes[f"nodes/{NODE}/qemu/101/status/current"]["name"] = "vm-renamed"
    coordinator = entry.runtime_data[COORDINATORS][f"{ProxmoxType.QEMU}_101"]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    device = dev_reg.async_get_device_by_identifier(identifier, entry.entry_id)
    assert device is not None
    assert device.name_by_user == "The one in the cellar"
    assert device.name == "QEMU vm-renamed (101)"


async def test_a_rename_leaves_the_entity_ids_alone(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """
    Test the entities are renamed, not re-registered.

    An entity id is the one thing automations, dashboards and history refer
    to, so it is never rewritten - not by the entity id scheme, and not
    here. What follows is the displayed name, which Home Assistant composes
    from the device's.
    """
    entry = await _setup(hass, fake_api, current_entry)
    ent_reg = er.async_get(hass)
    entity_id = "sensor.lxc_lxc_test_100_100_cpu_used"
    before = sorted(
        entity.entity_id
        for entity in er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    )
    assert entity_id in before

    fake_api.routes[f"nodes/{NODE}/lxc/100/status/current"]["name"] = "qv-test"
    coordinator = entry.runtime_data[COORDINATORS][f"{ProxmoxType.LXC}_100"]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    after = sorted(
        entity.entity_id
        for entity in er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    )
    assert after == before
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.attributes["friendly_name"] == "LXC qv-test (100) CPU used"
