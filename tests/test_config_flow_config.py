"""Test the Proxmox VE config flow."""

from unittest.mock import patch

import proxmoxer
from homeassistant.config_entries import (
    SOURCE_USER,
)
from homeassistant.const import (
    CONF_HOST,
    CONF_PORT,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from requests.exceptions import ConnectTimeout, SSLError

from custom_components.proxmoxve import DOMAIN

from .const import (
    MOCK_GET_RESPONSE,
    USER_INPUT_OK,
    USER_INPUT_PORT_TOO_BIG,
    USER_INPUT_PORT_TOO_SMALL,
    USER_INPUT_SELECTION,
    USER_INPUT_USER_HOST,
)


async def test_flow_ok(hass: HomeAssistant) -> None:
    """Test flow ok."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "host"

    with (
        patch("proxmoxer.ProxmoxResource.get", return_value=MOCK_GET_RESPONSE),
        patch(
            "proxmoxer.backends.https.ProxmoxHTTPAuth._get_new_tokens",
            return_value=None,
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=USER_INPUT_USER_HOST,
        )

        assert result["step_id"] == "expose"
        assert result["type"] == FlowResultType.FORM
        assert "flow_id" in result

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=USER_INPUT_SELECTION,
        )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert "data" in result
        assert result["data"][CONF_HOST] == USER_INPUT_USER_HOST[CONF_HOST]


async def test_flow_port_small(hass: HomeAssistant) -> None:
    """Test if port number too small."""
    with patch(
        "proxmoxer.backends.https.ProxmoxHTTPAuth._get_new_tokens", return_value=None
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
            data=USER_INPUT_PORT_TOO_SMALL,
        )

        assert result["type"] == FlowResultType.FORM
        assert result["errors"][CONF_PORT] == "invalid_port"


async def test_flow_port_big(hass: HomeAssistant) -> None:
    """Test if port number too big."""
    with patch(
        "proxmoxer.backends.https.ProxmoxHTTPAuth._get_new_tokens", return_value=None
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
            data=USER_INPUT_PORT_TOO_BIG,
        )

        assert result["type"] == FlowResultType.FORM
        assert result["errors"][CONF_PORT] == "invalid_port"


async def test_flow_auth_error(hass: HomeAssistant) -> None:
    """Test errors in case username or password are incorrect."""
    with patch(
        "custom_components.proxmoxve.ProxmoxClient.build_client",
        side_effect=proxmoxer.backends.https.AuthenticationError("mock msg"),
        return_value=None,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT_OK
        )

        assert result["type"] == FlowResultType.FORM
        assert result["errors"][CONF_USERNAME] == "auth_error"


async def test_flow_cant_connect(hass: HomeAssistant) -> None:
    """Test errors in case the connection fails."""
    with patch(
        "custom_components.proxmoxve.ProxmoxClient.build_client",
        side_effect=ConnectTimeout,
        return_value=None,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT_OK
        )

        assert result["type"] == FlowResultType.FORM
        assert result["errors"][CONF_HOST] == "cant_connect"


async def test_flow_ssl_error(hass: HomeAssistant) -> None:
    """Test errors in case the SSL certificare is not present or is not valid or is expired."""
    with patch(
        "custom_components.proxmoxve.ProxmoxClient.build_client",
        side_effect=SSLError,
        return_value=None,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT_OK
        )

        assert result["type"] == FlowResultType.FORM
        assert result["errors"][CONF_VERIFY_SSL] == "ssl_rejection"


async def test_flow_unknown_exception(hass: HomeAssistant) -> None:
    """Test errors in case of an unknown exception occurs."""
    with patch(
        "custom_components.proxmoxve.ProxmoxClient.build_client",
        side_effect=Exception,
        return_value=None,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
            data=USER_INPUT_OK,
        )

        assert result["type"] == FlowResultType.FORM
        assert result["errors"]["base"] == "general_error"


async def test_flow_already_configured(hass: HomeAssistant) -> None:
    """Test flow in case entry already configured."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=USER_INPUT_OK,
    )

    entry.add_to_hass(hass)

    with (
        patch("proxmoxer.ProxmoxResource.get", return_value=MOCK_GET_RESPONSE),
        patch(
            "proxmoxer.backends.https.ProxmoxHTTPAuth._get_new_tokens",
            return_value=None,
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
            data=USER_INPUT_USER_HOST,
        )

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "already_configured"
