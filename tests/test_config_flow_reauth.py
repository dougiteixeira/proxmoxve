"""Test the Proxmox VE config flow."""

from unittest.mock import patch

import proxmoxer
from homeassistant.config_entries import (
    SOURCE_REAUTH,
)
from homeassistant.const import (
    CONF_BASE,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from requests.exceptions import ConnectTimeout, SSLError

from custom_components.proxmoxve import DOMAIN

from .const import (
    USER_INPUT_AUTH,
    USER_INPUT_OK,
)


async def test_step_reauth(hass: HomeAssistant) -> None:
    """Test the reauth flow."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=USER_INPUT_OK,
    )

    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": SOURCE_REAUTH,
            "entry_id": entry.entry_id,
            "unique_id": entry.unique_id,
        },
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert "flow_id" in result

    with patch(
        "custom_components.proxmoxve.ProxmoxClient.build_client",
        return_value=True,
    ):
        result_auth_ok = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=USER_INPUT_AUTH
        )
        assert result_auth_ok["type"] == FlowResultType.ABORT
        assert result_auth_ok["reason"] == "reauth_successful"

        assert len(hass.config_entries.async_entries()) == 1

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": SOURCE_REAUTH,
            "entry_id": entry.entry_id,
            "unique_id": entry.unique_id,
        },
    )

    with patch(
        "custom_components.proxmoxve.ProxmoxClient.build_client",
        side_effect=proxmoxer.backends.https.AuthenticationError("mock msg"),
        return_value=None,
    ):
        result_auth_error = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=USER_INPUT_AUTH
        )
        assert result_auth_error["type"] == FlowResultType.FORM
        assert result_auth_error["errors"][CONF_USERNAME] == "auth_error"

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": SOURCE_REAUTH,
            "entry_id": entry.entry_id,
            "unique_id": entry.unique_id,
        },
    )

    with patch(
        "custom_components.proxmoxve.ProxmoxClient.build_client",
        side_effect=SSLError,
        return_value=None,
    ):
        result_auth_ssl_rejection = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=USER_INPUT_AUTH
        )
        assert result_auth_ssl_rejection["type"] == FlowResultType.FORM
        assert result_auth_ssl_rejection["errors"][CONF_BASE] == "ssl_rejection"

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": SOURCE_REAUTH,
            "entry_id": entry.entry_id,
            "unique_id": entry.unique_id,
        },
    )

    with patch(
        "custom_components.proxmoxve.ProxmoxClient.build_client",
        side_effect=ConnectTimeout,
        return_value=None,
    ):
        result_auth_ssl_rejectio = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=USER_INPUT_AUTH
        )
        assert result_auth_ssl_rejectio["type"] == FlowResultType.FORM
        assert result_auth_ssl_rejectio["errors"][CONF_BASE] == "cant_connect"

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": SOURCE_REAUTH,
            "entry_id": entry.entry_id,
            "unique_id": entry.unique_id,
        },
    )

    with patch(
        "custom_components.proxmoxve.ProxmoxClient.build_client",
        side_effect=Exception,
        return_value=None,
    ):
        result_auth_ssl_rejectio = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=USER_INPUT_AUTH
        )
        assert result_auth_ssl_rejectio["type"] == FlowResultType.FORM
        assert result_auth_ssl_rejectio["errors"][CONF_BASE] == "general_error"
