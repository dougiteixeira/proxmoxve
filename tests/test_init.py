"""Tests for the openid_auth_provider component."""

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
)

from .conftest import (
    CONST_CLIENT_ID,
)


async def test_no_config_entry(
    hass: HomeAssistant,
) -> None:
    """Test the auth provider is not enabled when no config entry is set up."""
    manager = hass.auth
    assert manager.auth_providers == []


async def test_init(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """Test login flow with emails."""
    manager = hass.auth

    assert {provider.id: provider.name for provider in manager.auth_providers} == {
        CONST_CLIENT_ID: "Example"
    }

    # Unload the config entry and verify the provider is unloaded
    await hass.config_entries.async_unload(config_entry.entry_id)
    assert [provider.id for provider in manager.auth_providers] == []
