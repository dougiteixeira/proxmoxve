"""Fixtures for the custom component."""

import logging
from collections.abc import AsyncGenerator, Generator
from unittest.mock import patch

import pytest
from homeassistant.const import CONF_NAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
)

from custom_components.proxmoxve.const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_CONFIGURATION,
    CONF_EMAILS,
    CONF_SUBJECTS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

CONST_DESCRIPTION_URI = "https://openid.test/.well-known/openid-configuration"
CONST_CLIENT_ID = "123client_id456"
CONST_CLIENT_SECRET = "123client_secret456"
CONST_SUBJECT = "248289761001"
CONST_EMAIL = "john.doe@openid.test"


CONST_JWKS_URI = "https://jwks.test/jwks"
CONST_JWKS_KEY = "bla"
CONST_JWKS = {"keys": [CONST_JWKS_KEY]}
CONST_AUTHORIZATION_ENDPOINT = "https://openid.test/authorize"
CONST_TOKEN_ENDPOINT = "https://openid.test/authorize"

CONST_DESCRIPTION = {
    "issuer": "https://openid.test/",
    "jwks_uri": CONST_JWKS_URI,
    "authorization_endpoint": CONST_AUTHORIZATION_ENDPOINT,
    "token_endpoint": CONST_TOKEN_ENDPOINT,
    "token_endpoint_auth_methods_supported": "client_secret_post",
    "id_token_signing_alg_values_supported": ["RS256", "HS256"],
    "scopes_supported": ["openid", "email", "profile"],
    "response_types_supported": "code",
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> Generator[None, None, None]:
    """Enable custom integration."""
    _ = enable_custom_integrations  # unused
    return


@pytest.fixture(name="platforms")
def mock_platforms() -> list[Platform]:
    """Fixture for platforms loaded by the integration."""
    return []


@pytest.fixture(name="setup_integration")
async def mock_setup_integration(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    platforms: list[Platform],
) -> AsyncGenerator[
    None,
    None,
]:
    """Set up the integration."""
    with patch(f"custom_components.{DOMAIN}.PLATFORMS", platforms):
        assert await async_setup_component(hass, DOMAIN, {})
        await hass.async_block_till_done()
        yield


@pytest.fixture(name="emails")
def mock_emails() -> list[str]:
    """Fixture for emails."""
    return [CONST_EMAIL]


@pytest.fixture(name="subjects")
def mock_subjects() -> list[str]:
    """Fixture for subjects."""
    return [CONST_SUBJECT]


@pytest.fixture(name="config_entry")
async def mock_config_entry(
    hass: HomeAssistant,
    emails: list[str],
    subjects: list[str],
) -> MockConfigEntry:
    """Fixture to create a configuration entry."""
    config_entry = MockConfigEntry(
        data={},
        domain=DOMAIN,
        options={
            CONF_NAME: "Example",
            CONF_CONFIGURATION: CONST_DESCRIPTION_URI,
            CONF_CLIENT_ID: CONST_CLIENT_ID,
            CONF_CLIENT_SECRET: CONF_CLIENT_SECRET,
            CONF_SUBJECTS: subjects,
            CONF_EMAILS: emails,
        },
        unique_id=CONST_CLIENT_ID,
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry
