"""Test the Proxmox VE config flow."""

from unittest.mock import patch

import proxmoxer
from homeassistant.config_entries import (
    SOURCE_IMPORT,
)
from homeassistant.const import (
    CONF_HOST,
    CONF_PORT,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry
from requests.exceptions import ConnectTimeout, SSLError

from custom_components.proxmoxve import DOMAIN
from custom_components.proxmoxve.const import (
    CONF_NODE,
    CONF_NODES,
)

from .const import (
    MOCK_GET_RESPONSE,
    USER_INPUT_USER_HOST,
    YAML_INPUT_NOT_EXIST,
    YAML_INPUT_OK,
)


async def test_flow_import_ok(hass: HomeAssistant) -> None:
    """Test import flow ok."""
    with (
        patch("proxmoxer.ProxmoxResource.get", return_value=MOCK_GET_RESPONSE),
        patch(
            "proxmoxer.backends.https.ProxmoxHTTPAuth._get_new_tokens",
            return_value=None,
        ),
    ):
        # imported config is identical to the one generated from config flow
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_IMPORT},
            data=YAML_INPUT_OK,
        )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert "data" in result
        assert result["data"][CONF_HOST] == YAML_INPUT_OK[CONF_HOST]

        issue_registry = ir.async_get(hass)
        assert (
            issue_registry.async_get_issue(
                DOMAIN,
                f"{YAML_INPUT_OK.get(CONF_HOST)}_{YAML_INPUT_OK.get(CONF_PORT)}_import_success",
            )
            is not None
        )


async def test_flow_import_error_node_not_exist(hass: HomeAssistant) -> None:
    """Test import error in case node not exist in Proxmox."""
    with (
        patch("proxmoxer.ProxmoxResource.get", return_value=MOCK_GET_RESPONSE),
        patch(
            "proxmoxer.backends.https.ProxmoxHTTPAuth._get_new_tokens",
            return_value=None,
        ),
    ):
        # imported config is identical to the one generated from config flow
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_IMPORT}, data=YAML_INPUT_NOT_EXIST
        )

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "import_failed"

        issue_registry = ir.async_get(hass)
        for nodes in YAML_INPUT_NOT_EXIST.get(CONF_NODES):
            assert (
                issue_registry.async_get_issue(
                    DOMAIN,
                    f"{YAML_INPUT_NOT_EXIST.get(CONF_HOST)}_{YAML_INPUT_NOT_EXIST.get(CONF_PORT)}_{nodes[CONF_NODE]}_import_node_not_exist",
                )
                is not None
            )


async def test_flow_import_error_auth_error(hass: HomeAssistant) -> None:
    """Test import errors in case username or password are incorrect."""
    with patch(
        "custom_components.proxmoxve.ProxmoxClient.build_client",
        side_effect=proxmoxer.backends.https.AuthenticationError("mock msg"),
        return_value=None,
    ):
        # imported config is identical to the one generated from config flow
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_IMPORT}, data=YAML_INPUT_OK
        )

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "import_failed"

        issue_registry = ir.async_get(hass)
        assert (
            issue_registry.async_get_issue(
                DOMAIN,
                f"{YAML_INPUT_OK.get(CONF_HOST)}_{YAML_INPUT_OK.get(CONF_PORT)}_import_auth_error",
            )
            is not None
        )


async def test_flow_import_error_ssl_rejection(hass: HomeAssistant) -> None:
    """Test import errors in case the SSL certificare is not present or is not valid or is expired."""
    with patch(
        "custom_components.proxmoxve.ProxmoxClient.build_client",
        side_effect=SSLError,
        return_value=None,
    ):
        # imported config is identical to the one generated from config flow
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_IMPORT}, data=USER_INPUT_USER_HOST
        )

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "import_failed"

        issue_registry = ir.async_get(hass)
        assert (
            issue_registry.async_get_issue(
                DOMAIN,
                f"{YAML_INPUT_OK.get(CONF_HOST)}_{YAML_INPUT_OK.get(CONF_PORT)}_import_ssl_rejection",
            )
            is not None
        )


async def test_flow_import_error_cant_connect(hass: HomeAssistant) -> None:
    """Test import errors in case the connection fails."""
    with patch(
        "custom_components.proxmoxve.ProxmoxClient.build_client",
        side_effect=ConnectTimeout,
        return_value=None,
    ):
        # imported config is identical to the one generated from config flow
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_IMPORT}, data=YAML_INPUT_OK
        )

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "import_failed"

        issue_registry = ir.async_get(hass)
        assert (
            issue_registry.async_get_issue(
                DOMAIN,
                f"{YAML_INPUT_OK.get(CONF_HOST)}_{YAML_INPUT_OK.get(CONF_PORT)}_import_cant_connect",
            )
            is not None
        )


async def test_flow_import_error_general_error(hass: HomeAssistant) -> None:
    """Test import errors in case of an unknown exception occurs."""
    with patch(
        "custom_components.proxmoxve.ProxmoxClient.build_client",
        side_effect=Exception,
        return_value=None,
    ):
        # imported config is identical to the one generated from config flow
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_IMPORT}, data=YAML_INPUT_OK
        )

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "import_failed"

        issue_registry = ir.async_get(hass)
        assert (
            issue_registry.async_get_issue(
                DOMAIN,
                f"{YAML_INPUT_OK.get(CONF_HOST)}_{YAML_INPUT_OK.get(CONF_PORT)}_import_general_error",
            )
            is not None
        )


async def test_flow_import_error_already_configured(hass: HomeAssistant) -> None:
    """Test import error in case entry already configured."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=YAML_INPUT_OK,
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
            context={"source": SOURCE_IMPORT},
            data=YAML_INPUT_OK,
        )

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "import_failed"

        issue_registry = ir.async_get(hass)
        assert (
            issue_registry.async_get_issue(
                DOMAIN,
                f"{YAML_INPUT_OK.get(CONF_HOST)}_{YAML_INPUT_OK.get(CONF_PORT)}_import_already_configured",
            )
            is not None
        )
