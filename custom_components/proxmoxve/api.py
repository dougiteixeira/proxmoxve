"""Handle API for Proxmox VE."""

from typing import Any

from proxmoxer import ProxmoxAPI
from proxmoxer.core import ResourceException
from requests.exceptions import ConnectTimeout

from homeassistant.const import CONF_USERNAME
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir

from .const import (
    DEFAULT_PORT,
    DEFAULT_REALM,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    LOGGER,
    ProxmoxCommand,
    ProxmoxType,
)


class ProxmoxClient:
    """A wrapper for the proxmoxer ProxmoxAPI client."""

    _proxmox: ProxmoxAPI

    def __init__(
        self,
        host: str,
        user: str,
        password: str,
        port: int | None = DEFAULT_PORT,
        realm: str | None = DEFAULT_REALM,
        verify_ssl: bool | None = DEFAULT_VERIFY_SSL,
    ) -> None:
        """Initialize the ProxmoxClient."""

        self._host = host
        self._port = port
        self._user = user
        self._realm = realm
        self._password = password
        self._verify_ssl = verify_ssl

    def build_client(self) -> None:
        """Construct the ProxmoxAPI client.

        Allows inserting the realm within the `user` value.
        """

        if "@" in self._user:
            user_id = self._user
        else:
            user_id = f"{self._user}@{self._realm}"

        self._proxmox = ProxmoxAPI(
            self._host,
            port=self._port,
            user=user_id,
            password=self._password,
            verify_ssl=self._verify_ssl,
            timeout=30,
        )

    def get_api_client(self) -> ProxmoxAPI:
        """Return the ProxmoxAPI client."""
        return self._proxmox


def get_api(
    proxmox: ProxmoxAPI,
    api_path: str,
) -> dict[str, Any] | None:
    """Return data from the Proxmox API."""

    api_result = proxmox.get(api_path)
    LOGGER.debug("API GET Response - %s: %s", api_path, api_result)
    return api_result


def post_api(
    proxmox: ProxmoxAPI,
    api_path: str,
) -> dict[str, Any] | None:
    """Post data to Proxmox API."""

    api_result = proxmox.post(api_path)
    LOGGER.debug("API POST - %s: %s", api_path, api_result)
    return api_result


def post_api_command(
    self,
    proxmox_client: ProxmoxClient,
    api_category: ProxmoxType,
    command: str,
    node: str,
    vm_id: int | None = None,
) -> Any:
    """Make proper api post status calls to set state."""
    result = None

    proxmox = proxmox_client.get_api_client()

    if command not in ProxmoxCommand:
        raise ValueError("Invalid Command")

    if api_category is ProxmoxType.Node:
        issue_id = f"{self.config_entry.entry_id}_{node}_command_forbiden"
    elif api_category in (ProxmoxType.QEMU, ProxmoxType.LXC):
        issue_id = f"{self.config_entry.entry_id}_{vm_id}_command_forbiden"

    try:
        # Only the START_ALL and STOP_ALL are not part of status API
        if api_category is ProxmoxType.Node and command in [
            ProxmoxCommand.START_ALL,
            ProxmoxCommand.STOP_ALL,
        ]:
            result = post_api(proxmox, f"nodes/{node}/{command}")
        elif api_category is ProxmoxType.Node:
            result = post_api(proxmox, f"nodes/{node}/status?command={command}")
        elif command == ProxmoxCommand.HIBERNATE:
            result = post_api(
                proxmox,
                f"nodes/{node}/{api_category}/{vm_id}/status/{ProxmoxCommand.SUSPEND}?todisk=1",
            )
        else:
            result = post_api(
                proxmox, f"nodes/{node}/{api_category}/{vm_id}/status/{command}"
            )

    except ResourceException as error:
        if error.status_code == 403:
            permissions = str(error).split("(")[1].split(",")
            permission_check = (
                f"['perm','{permissions[0]}',[{permissions[1].strip().strip(')')}]]"
            )
            if api_category is ProxmoxType.Node:
                resource = f"{api_category.capitalize()} {node}"
            elif api_category in (ProxmoxType.QEMU, ProxmoxType.LXC):
                resource = f"{api_category.upper()} {vm_id}"
            ir.create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="resource_command_forbiden",
                translation_placeholders={
                    "resource": resource,
                    "user": self.config_entry.data[CONF_USERNAME],
                    "permission": permission_check,
                    "command": command,
                },
            )
            raise HomeAssistantError(
                f"Proxmox {resource} {command} error - {error}",
            ) from error

    except ConnectTimeout as error:
        raise HomeAssistantError(
            f"Proxmox {resource} {command} error - {error}",
        ) from error

    ir.delete_issue(
        self.hass,
        DOMAIN,
        issue_id,
    )

    return result
