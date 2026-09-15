# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for migrating config entries from earlier versions."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.proxmoxve import DOMAIN
from custom_components.proxmoxve.const import (
    CONF_LXC,
    CONF_NODE,
    CONF_NODES,
    CONF_QEMU,
    CONF_REALM,
    CONF_STORAGE,
    CONF_TOKEN_NAME,
)

from .const import CURRENT_ENTRY_VERSION
from .fake_api import FakeProxmox

# What the very first config flow stored: one node under a singular key.
VERSION_1_DATA = {
    CONF_HOST: "192.168.10.101",
    CONF_PORT: 8006,
    CONF_USERNAME: "root",
    CONF_TOKEN_NAME: "",
    CONF_PASSWORD: "secret",
    CONF_REALM: "pam",
    CONF_VERIFY_SSL: True,
    CONF_NODE: "pve",
    CONF_QEMU: ["101"],
    CONF_LXC: ["100"],
}


async def test_a_version_1_entry_reaches_the_current_version(
    hass: HomeAssistant, fake_api: FakeProxmox
) -> None:
    """Test the whole chain of migrations keeps the node, guests and storages."""
    entry = MockConfigEntry(domain=DOMAIN, title="Test", data=VERSION_1_DATA, version=1)
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.version == CURRENT_ENTRY_VERSION
    assert entry.data[CONF_NODES] == ["pve"]
    assert entry.data[CONF_QEMU] == ["101"]
    assert entry.data[CONF_LXC] == ["100"]
    assert entry.data[CONF_STORAGE] == []
    assert entry.data[CONF_HOST] == "192.168.10.101"


async def test_migration_resets_the_options(
    hass: HomeAssistant, fake_api: FakeProxmox
) -> None:
    """
    Test - and document - that the early migrations drop the options.

    Every migration up to version 4 writes `options={}`. Entries that old
    predate every option this integration has, so nothing is lost; but a
    test that gives a version-1 entry options and expects them to survive
    setup will be surprised, which is why the setup tests use a current one.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        data=VERSION_1_DATA,
        options={"disks_enable": False},
        version=1,
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.options == {}
