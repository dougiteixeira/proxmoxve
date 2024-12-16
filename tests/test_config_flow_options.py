"""Test the Proxmox VE config flow."""

from unittest.mock import patch

import proxmoxer
from homeassistant.config_entries import (
    ConfigEntryState,
)
from homeassistant.const import (
    CONF_BASE,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from requests.exceptions import ConnectTimeout, SSLError

from custom_components.proxmoxve import DOMAIN
from custom_components.proxmoxve.const import (
    CONF_LXC,
    CONF_NODES,
    CONF_QEMU,
    CONF_REALM,
)

from . import async_init_integration, patch_async_setup_entry
from .const import (
    MOCK_GET_RESPONSE,
    USER_INPUT_OK,
    USER_INPUT_OPTION_AUTH,
    USER_INPUT_SELECTION,
    mock_config_entry,
)


async def test_options_flow_host_auth(hass: HomeAssistant) -> None:
    """Test options config flow."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        data=USER_INPUT_OK,
    )
    entry.add_to_hass(hass)

    with patch_async_setup_entry(return_value=True):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.options.async_init(entry.entry_id, data=None)
        await hass.async_block_till_done()

        assert result["type"] == FlowResultType.MENU
        assert result["step_id"] == "menu"

        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {"next_step_id": "host_auth"},
        )

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "host_auth"

        with patch(
            "custom_components.proxmoxve.ProxmoxClient.build_client",
            side_effect=proxmoxer.backends.https.AuthenticationError("mock msg"),
            return_value=None,
        ):
            result_auth_error = await hass.config_entries.options.async_configure(
                result["flow_id"],
                user_input=USER_INPUT_OPTION_AUTH,
            )
            assert result_auth_error["type"] == FlowResultType.FORM
            assert result_auth_error["errors"][CONF_USERNAME] == "auth_error"

        with patch(
            "custom_components.proxmoxve.ProxmoxClient.build_client",
            side_effect=SSLError,
            return_value=None,
        ):
            result_auth_ssl_rejection = (
                await hass.config_entries.options.async_configure(
                    result["flow_id"],
                    user_input=USER_INPUT_OPTION_AUTH,
                )
            )
            assert result_auth_ssl_rejection["type"] == FlowResultType.FORM
            assert (
                result_auth_ssl_rejection["errors"][CONF_VERIFY_SSL] == "ssl_rejection"
            )

        with patch(
            "custom_components.proxmoxve.ProxmoxClient.build_client",
            side_effect=ConnectTimeout,
            return_value=None,
        ):
            result_auth_cant_connect = (
                await hass.config_entries.options.async_configure(
                    result["flow_id"],
                    user_input=USER_INPUT_OPTION_AUTH,
                )
            )
            assert result_auth_cant_connect["type"] == FlowResultType.FORM
            assert result_auth_cant_connect["errors"][CONF_HOST] == "cant_connect"

        with patch(
            "custom_components.proxmoxve.ProxmoxClient.build_client",
            side_effect=Exception,
            return_value=None,
        ):
            result_auth_general_error = (
                await hass.config_entries.options.async_configure(
                    result["flow_id"],
                    user_input=USER_INPUT_OPTION_AUTH,
                )
            )
            assert result_auth_general_error["type"] == FlowResultType.FORM
            assert result_auth_general_error["errors"][CONF_BASE] == "general_error"

        with (
            patch("proxmoxer.ProxmoxResource.get", return_value=MOCK_GET_RESPONSE),
            patch(
                "proxmoxer.backends.https.ProxmoxHTTPAuth._get_new_tokens",
                return_value=None,
            ),
        ):
            result = await hass.config_entries.options.async_configure(
                result["flow_id"],
                user_input=USER_INPUT_OPTION_AUTH,
            )

            assert result["type"] == FlowResultType.ABORT
            assert result["reason"] == "changes_successful"

            result = hass.config_entries.async_get_entry(entry.entry_id)
            assert entry.data[CONF_USERNAME] == USER_INPUT_OPTION_AUTH[CONF_USERNAME]


async def test_options_flow_change_expose(hass: HomeAssistant) -> None:
    """Test options config flow."""
    with (
        patch("proxmoxer.ProxmoxResource.get", return_value=MOCK_GET_RESPONSE),
        patch(
            "proxmoxer.backends.https.ProxmoxHTTPAuth._get_new_tokens",
            return_value=None,
        ),
    ):
        await async_init_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED

    with (
        patch("proxmoxer.ProxmoxResource.get", return_value=MOCK_GET_RESPONSE),
        patch(
            "proxmoxer.backends.https.ProxmoxHTTPAuth._get_new_tokens",
            return_value=None,
        ),
    ):
        result = await hass.config_entries.options.async_init(
            mock_config_entry.entry_id, data=None
        )
        await hass.async_block_till_done()

        assert result["type"] == FlowResultType.MENU
        assert result["step_id"] == "menu"

        with (
            patch("proxmoxer.ProxmoxResource.get", return_value=MOCK_GET_RESPONSE),
            patch(
                "proxmoxer.backends.https.ProxmoxHTTPAuth._get_new_tokens",
                return_value=None,
            ),
        ):
            result = await hass.config_entries.options.async_configure(
                result["flow_id"],
                {"next_step_id": "change_expose"},
            )

            assert result["type"] == FlowResultType.FORM
            assert result["step_id"] == "change_expose"

            result = await hass.config_entries.options.async_configure(
                result["flow_id"],
                user_input=USER_INPUT_SELECTION,
            )

            assert result["type"] == FlowResultType.ABORT
            assert result["reason"] == "changes_successful"


async def test_options_flow_change_expose_auth_error(hass: HomeAssistant) -> None:
    """Test options config flow."""
    mock_config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        data={
            CONF_HOST: "192.168.10.102",
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

    with (
        patch("proxmoxer.ProxmoxResource.get", return_value=MOCK_GET_RESPONSE),
        patch(
            "proxmoxer.backends.https.ProxmoxHTTPAuth._get_new_tokens",
            return_value=None,
        ),
    ):
        result = await hass.config_entries.options.async_init(
            mock_config_entry.entry_id, data=None
        )
        await hass.async_block_till_done()

        assert result["type"] == FlowResultType.MENU
        assert result["step_id"] == "menu"

        with patch(
            "custom_components.proxmoxve.ProxmoxClient.build_client",
            side_effect=proxmoxer.backends.https.AuthenticationError("mock msg"),
            return_value=None,
        ):
            result = await hass.config_entries.options.async_configure(
                result["flow_id"],
                {"next_step_id": "change_expose"},
            )

            assert result["type"] == FlowResultType.ABORT
            assert result["reason"] == "auth_error"


async def test_options_flow_change_expose_ssl_rejection(hass: HomeAssistant) -> None:
    """Test options config flow."""
    mock_config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        data={
            CONF_HOST: "192.168.10.103",
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

    with (
        patch("proxmoxer.ProxmoxResource.get", return_value=MOCK_GET_RESPONSE),
        patch(
            "proxmoxer.backends.https.ProxmoxHTTPAuth._get_new_tokens",
            return_value=None,
        ),
    ):
        result = await hass.config_entries.options.async_init(
            mock_config_entry.entry_id, data=None
        )
        await hass.async_block_till_done()

        assert result["type"] == FlowResultType.MENU
        assert result["step_id"] == "menu"

        with patch(
            "custom_components.proxmoxve.ProxmoxClient.build_client",
            side_effect=SSLError,
            return_value=None,
        ):
            result = await hass.config_entries.options.async_configure(
                result["flow_id"],
                {"next_step_id": "change_expose"},
            )

            assert result["type"] == FlowResultType.ABORT
            assert result["reason"] == "ssl_rejection"


async def test_options_flow_change_expose_cant_connect(hass: HomeAssistant) -> None:
    """Test options config flow."""
    mock_config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        data={
            CONF_HOST: "192.168.10.104",
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

    with (
        patch("proxmoxer.ProxmoxResource.get", return_value=MOCK_GET_RESPONSE),
        patch(
            "proxmoxer.backends.https.ProxmoxHTTPAuth._get_new_tokens",
            return_value=None,
        ),
    ):
        result = await hass.config_entries.options.async_init(
            mock_config_entry.entry_id, data=None
        )
        await hass.async_block_till_done()

        assert result["type"] == FlowResultType.MENU
        assert result["step_id"] == "menu"

        with patch(
            "custom_components.proxmoxve.ProxmoxClient.build_client",
            side_effect=ConnectTimeout,
            return_value=None,
        ):
            result = await hass.config_entries.options.async_configure(
                result["flow_id"],
                {"next_step_id": "change_expose"},
            )

            assert result["type"] == FlowResultType.ABORT
            assert result["reason"] == "cant_connect"


async def test_options_flow_change_expose_general_error(hass: HomeAssistant) -> None:
    """Test options config flow."""
    mock_config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        data={
            CONF_HOST: "192.168.10.105",
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

    with (
        patch("proxmoxer.ProxmoxResource.get", return_value=MOCK_GET_RESPONSE),
        patch(
            "proxmoxer.backends.https.ProxmoxHTTPAuth._get_new_tokens",
            return_value=None,
        ),
    ):
        result = await hass.config_entries.options.async_init(
            mock_config_entry.entry_id, data=None
        )
        await hass.async_block_till_done()

        assert result["type"] == FlowResultType.MENU
        assert result["step_id"] == "menu"

        with patch(
            "custom_components.proxmoxve.ProxmoxClient.build_client",
            side_effect=Exception,
            return_value=None,
        ):
            result = await hass.config_entries.options.async_configure(
                result["flow_id"],
                {"next_step_id": "change_expose"},
            )

            assert result["type"] == FlowResultType.ABORT
            assert result["reason"] == "general_error"
