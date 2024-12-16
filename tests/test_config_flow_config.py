"""Test the Proxmox VE config flow."""

from unittest.mock import patch

import proxmoxer
from homeassistant.config_entries import (
    SOURCE_USER,
)
from homeassistant.const import (
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

USER_INPUT_OK = {
    CONF_HOST: "192.168.10.101",
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
    CONF_STORAGE: ["storage/pve/local"],
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
