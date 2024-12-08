"""Tests for the config flow."""

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.const import (
    CONF_NAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.openid_auth_provider.const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_CONFIGURATION,
    CONF_EMAILS,
    DOMAIN,
)

from .conftest import CONST_DESCRIPTION, CONST_DESCRIPTION_URI


async def test_config_flow(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test completing the configuration flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result.get("type") is FlowResultType.FORM
    assert result.get("errors") is None

    aioclient_mock.get(
        CONST_DESCRIPTION_URI,
        json=CONST_DESCRIPTION,
    )

    with patch(
        f"custom_components.{DOMAIN}.async_setup_entry", return_value=True
    ) as mock_setup:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_NAME: "Example",
                CONF_CONFIGURATION: CONST_DESCRIPTION_URI,
                CONF_CLIENT_ID: "client-id",
                CONF_CLIENT_SECRET: "client-secret",
                CONF_EMAILS: ["user@dex.local", "user@dex.remote"],
            },
        )
        await hass.async_block_till_done()

    assert result.get("type") is FlowResultType.CREATE_ENTRY
    assert result.get("title") == "Example"
    assert result.get("context", {}).get("unique_id") == "client-id"
    assert result.get("data") == {}
    assert result.get("options") == {
        CONF_NAME: "Example",
        CONF_CONFIGURATION: CONST_DESCRIPTION_URI,
        CONF_CLIENT_ID: "client-id",
        CONF_CLIENT_SECRET: "client-secret",
        CONF_EMAILS: ["user@dex.local", "user@dex.remote"],
    }
    assert len(mock_setup.mock_calls) == 1
