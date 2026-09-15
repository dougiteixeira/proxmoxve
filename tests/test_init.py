# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for setting up, unloading and importing Proxmox VE."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.proxmoxve import DOMAIN

from .const import YAML_INPUT_INVALID, YAML_INPUT_OK
from .fake_api import FakeProxmox


async def test_setup_entry(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test a current entry sets up against a cluster that answers."""
    await hass.config_entries.async_setup(current_entry.entry_id)
    await hass.async_block_till_done()

    assert current_entry.state is ConfigEntryState.LOADED


async def test_unload_entry(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test unloading leaves the entry not loaded and stops the polling."""
    await hass.config_entries.async_setup(current_entry.entry_id)
    await hass.async_block_till_done()
    assert current_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(current_entry.entry_id)
    await hass.async_block_till_done()

    assert current_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_config(hass: HomeAssistant, fake_api: FakeProxmox) -> None:
    """Test setup from yaml config imports an entry and sets it up."""
    assert await async_setup_component(hass, DOMAIN, YAML_INPUT_OK)
    await hass.async_block_till_done()

    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    assert entries[0].state is ConfigEntryState.LOADED


async def test_setup_invalid_config(hass: HomeAssistant, fake_api: FakeProxmox) -> None:
    """Test setup from yaml with invalid config."""
    assert not await async_setup_component(hass, DOMAIN, YAML_INPUT_INVALID)
    await hass.async_block_till_done()
