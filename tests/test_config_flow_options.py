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
    CONF_CONTAINERS,
    CONF_DISKS_ENABLE,
    CONF_LXC,
    CONF_NODE,
    CONF_NODES,
    CONF_QEMU,
    CONF_REALM,
    CONF_STORAGE,
    CONF_TOKEN_NAME,
    CONF_VMS,
)

from . import async_init_integration, patch_async_setup_entry

USER_INPUT_OK = {
    CONF_HOST: "192.168.10.100",
    CONF_STORAGE: ["storage/pve/local", "xxx"],
    CONF_PORT: 8006,
    CONF_USERNAME: "root",
    CONF_PASSWORD: "secret",
    CONF_REALM: "pam",
    CONF_VERIFY_SSL: True,
    CONF_NODES: ["pve"],
    CONF_QEMU: ["101"],
    CONF_LXC: ["100"],
}
YAML_INPUT_OK = {
    CONF_HOST: "192.168.10.101",
    CONF_PORT: 8006,
    CONF_USERNAME: "root",
    CONF_PASSWORD: "secret",
    CONF_REALM: "pam",
    CONF_VERIFY_SSL: True,
    CONF_NODE: "pve",
    CONF_QEMU: ["100", "101", "102"],
    CONF_LXC: ["201", "202", "203"],
}
USER_INPUT_USER_HOST = {
    CONF_HOST: "192.168.10.101",
    CONF_PORT: 8006,
    CONF_USERNAME: "root",
    CONF_PASSWORD: "secret",
    CONF_REALM: "pam",
    CONF_VERIFY_SSL: True,
}
USER_INPUT_SELECTION = {
    CONF_NODES: ["pve"],
    CONF_QEMU: ["101"],
    CONF_LXC: ["100"],
    CONF_STORAGE: ["storage/pve/ext"],
    CONF_DISKS_ENABLE: True,
}
USER_INPUT_AUTH = {
    CONF_USERNAME: "root",
    CONF_PASSWORD: "secret",
    CONF_REALM: "pam",
}
USER_INPUT_OPTION_AUTH = {
    CONF_USERNAME: "root",
    CONF_TOKEN_NAME: "",
    CONF_PASSWORD: "secret",
    CONF_REALM: "pam",
    CONF_VERIFY_SSL: True,
}
USER_INPUT_NOT_EXIST = {
    CONF_HOST: "192.168.10.101",
    CONF_PORT: 8006,
    CONF_USERNAME: "root",
    CONF_PASSWORD: "secret",
    CONF_REALM: "pam",
    CONF_VERIFY_SSL: True,
    CONF_NODES: ["not_exist"],
    CONF_VMS: ["100", "101"],
    CONF_CONTAINERS: ["201", "202"],
}
USER_INPUT_PORT_TOO_BIG = {
    CONF_HOST: "192.168.10.101",
    CONF_PORT: 255555,
    CONF_USERNAME: "root",
    CONF_PASSWORD: "secret",
    CONF_REALM: "pam",
    CONF_VERIFY_SSL: True,
}
USER_INPUT_PORT_TOO_SMALL = {
    CONF_HOST: "192.168.10.101",
    CONF_PORT: 0,
    CONF_USERNAME: "root",
    CONF_PASSWORD: "secret",
    CONF_REALM: "pam",
    CONF_VERIFY_SSL: True,
}

MOCK_GET_RESPONSE = [
    {
        "status": "running",
        "cpu": 0.000317945887924996,
        "maxmem": 1073741824,
        "maxcpu": 2,
        "uptime": 309943,
        "id": "lxc/100",
        "diskwrite": 100974592,
        "vmid": 100,
        "netout": 117493824,
        "netin": 370783656,
        "template": 0,
        "node": "pve",
        "type": "lxc",
        "maxdisk": 2040373248,
        "disk": 911167488,
        "diskread": 983932928,
        "mem": 18821120,
        "name": "lxc-test-100",
    },
    {
        "status": "running",
        "cpu": 0.000317945887924996,
        "maxmem": 1073741824,
        "maxcpu": 2,
        "uptime": 309943,
        "id": "lxc/4000",
        "diskwrite": 100974592,
        "vmid": 4000,
        "netout": 117493824,
        "netin": 370783656,
        "template": 0,
        "node": "pve",
        "type": "lxc",
        "maxdisk": 2040373248,
        "disk": 911167488,
        "diskread": 983932928,
        "mem": 18821120,
    },
    {
        "template": 0,
        "node": "pve",
        "type": "qemu",
        "maxdisk": 0,
        "disk": 0,
        "diskread": 3157159936,
        "mem": 3519520768,
        "status": "running",
        "cpu": 0.0482256046823613,
        "maxmem": 8589934592,
        "maxcpu": 4,
        "uptime": 309941,
        "id": "qemu/999",
        "diskwrite": 18522621440,
        "vmid": 999,
        "netout": 31171753430,
        "netin": 90068966355,
    },
    {
        "template": 0,
        "node": "pve",
        "type": "qemu",
        "maxdisk": 0,
        "disk": 0,
        "diskread": 3157159936,
        "mem": 3519520768,
        "name": "vm-test-101",
        "status": "running",
        "cpu": 0.0482256046823613,
        "maxmem": 8589934592,
        "maxcpu": 4,
        "uptime": 309941,
        "id": "qemu/101",
        "diskwrite": 18522621440,
        "vmid": 101,
        "netout": 31171753430,
        "netin": 90068966355,
    },
    {
        "maxdisk": 100861726720,
        "node": "pve",
        "type": "node",
        "level": "",
        "mem": 8082927616,
        "disk": 14395695104,
        "cgroup-mode": 2,
        "id": "node/pve",
        "maxcpu": 4,
        "uptime": 310001,
        "maxmem": 16542171136,
        "status": "online",
        "cpu": 0.0712166172106825,
    },
    {
        "disk": 414336409600,
        "plugintype": "dir",
        "content": "backup,images,vztmpl,snippets,iso,rootdir",
        "shared": 0,
        "status": "available",
        "type": "storage",
        "node": "pve",
        "id": "storage/pve/ext",
        "maxdisk": 471416549376,
        "storage": "ext",
    },
    {
        "storage": "local",
        "id": "storage/pve/local",
        "maxdisk": 100861726720,
        "status": "available",
        "type": "storage",
        "node": "pve",
        "shared": 0,
        "disk": 14395699200,
        "plugintype": "dir",
        "content": "backup,snippets,iso,images,vztmpl,rootdir",
    },
    {
        "id": "sdn/pve/localnetwork",
        "status": "ok",
        "sdn": "localnetwork",
        "node": "pve",
        "type": "sdn",
    },
]

mock_config_entry = MockConfigEntry(
    domain=DOMAIN,
    title="Test",
    data=USER_INPUT_OK,
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
