"""Tests for Proxmox VE."""

from unittest.mock import patch

from homeassistant.config_entries import (
    ConfigEntryState,
)
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.proxmoxve import DOMAIN
from custom_components.proxmoxve.const import (
    CONF_LXC,
    CONF_NODES,
    CONF_QEMU,
    CONF_REALM,
)

from . import async_init_integration
from .const import (
    MOCK_GET_RESPONSE,
    YAML_INPUT_INVALID,
    YAML_INPUT_OK,
)


async def test_setup_entry(hass: HomeAssistant) -> None:
    """Test setup entry."""
    mock_config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        data={
            CONF_HOST: "192.168.10.107",
            CONF_PORT: 8006,
            CONF_USERNAME: "root",
            CONF_PASSWORD: "secret",
            CONF_REALM: "pam",
            CONF_VERIFY_SSL: True,
            CONF_NODES: ["pve"],
            CONF_QEMU: ["101"],
            CONF_LXC: ["100"],
        },
    )
    with (
        patch("proxmoxer.ProxmoxResource.get", return_value=MOCK_GET_RESPONSE),
        patch(
            "proxmoxer.backends.https.ProxmoxHTTPAuth._get_new_tokens",
            return_value=None,
        ),
    ):
        await async_init_integration(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED


async def test_unload_entry(hass: HomeAssistant) -> None:
    """Test unload an entry."""
    mock_config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        data={
            CONF_HOST: "192.168.10.108",
            CONF_PORT: 8006,
            CONF_USERNAME: "root",
            CONF_PASSWORD: "secret",
            CONF_REALM: "pam",
            CONF_VERIFY_SSL: True,
            CONF_NODES: ["pve"],
            CONF_QEMU: ["101"],
            CONF_LXC: ["100"],
        },
    )
    with (
        patch("proxmoxer.ProxmoxResource.get", return_value=MOCK_GET_RESPONSE),
        patch(
            "proxmoxer.backends.https.ProxmoxHTTPAuth._get_new_tokens",
            return_value=None,
        ),
    ):
        await async_init_integration(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_config(hass: HomeAssistant) -> None:
    """Test setup from yaml config."""
    with (
        patch("proxmoxer.ProxmoxResource.get", return_value=MOCK_GET_RESPONSE),
        patch(
            "proxmoxer.backends.https.ProxmoxHTTPAuth._get_new_tokens",
            return_value=None,
        ),
    ):
        assert await async_setup_component(hass, DOMAIN, YAML_INPUT_OK)
        await hass.async_block_till_done()


async def test_setup_invalid_config(hass: HomeAssistant) -> None:
    """Test setup from yaml with invalid config."""
    with (
        patch("proxmoxer.ProxmoxResource.get", return_value=MOCK_GET_RESPONSE),
        patch(
            "proxmoxer.backends.https.ProxmoxHTTPAuth._get_new_tokens",
            return_value=None,
        ),
    ):
        assert not await async_setup_component(hass, DOMAIN, YAML_INPUT_INVALID)
        await hass.async_block_till_done()
