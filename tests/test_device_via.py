# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for how a device is linked to the node it lives on."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.proxmoxve import DOMAIN, device_info
from custom_components.proxmoxve.const import ProxmoxType

from .fake_api import FakeProxmox


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
