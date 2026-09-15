# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for how a device is linked to the node it lives on."""

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.proxmoxve import DOMAIN, device_info
from custom_components.proxmoxve.const import ProxmoxType

from . import async_init_integration
from .const import MOCK_GET_RESPONSE, USER_INPUT_OK


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    """Set up the integration against a mocked API and return its entry."""
    entry = MockConfigEntry(domain=DOMAIN, title="Test", data=USER_INPUT_OK)
    with (
        patch("proxmoxer.ProxmoxResource.get", return_value=MOCK_GET_RESPONSE),
        patch(
            "proxmoxer.backends.https.ProxmoxHTTPAuth._get_new_tokens",
            return_value=None,
        ),
    ):
        await async_init_integration(hass, entry)
    return entry


async def test_links_to_a_node_that_has_a_device(hass: HomeAssistant) -> None:
    """Test the parent id is filled in for a node that does have a device."""
    entry = await _setup(hass)
    node_identifier = (DOMAIN, f"{entry.entry_id}_{ProxmoxType.Node.upper()}_pve")
    node = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={node_identifier},
        name="Node pve",
    )

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
    hass: HomeAssistant,
) -> None:
    """
    Test no link is claimed to a node that has no device.

    Home Assistant reported a device created naming a parent that does not
    exist, and drops the link regardless. This happens for anything sitting on
    a node the user did not select. Leaving the link out loses nothing and
    keeps that report out of the log.
    """
    entry = await _setup(hass)

    info = device_info(
        hass=hass,
        config_entry=entry,
        api_category=ProxmoxType.ZFS,
        node="a-node-nobody-selected",
        resource_id="tank",
    )

    assert info["via_device_id"] is None
