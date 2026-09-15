# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Handle API for Proxmox VE."""

from typing import Any

from homeassistant.const import CONF_USERNAME
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from proxmoxer import ProxmoxAPI
from proxmoxer.core import ResourceException
from requests.adapters import HTTPAdapter
from requests.exceptions import ConnectTimeout

from .const import (
    CONF_HA_ADMIN_USERNAME,
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
        *,
        host: str,
        user: str,
        password: str,
        token_name: str = "",
        port: int | None = DEFAULT_PORT,
        realm: str | None = DEFAULT_REALM,
        verify_ssl: bool | None = DEFAULT_VERIFY_SSL,
    ) -> None:
        """Initialize the ProxmoxClient."""
        self._host = host
        self._port = port
        self._user = user
        self._token_name = token_name
        self._realm = realm
        self._password = password
        self._verify_ssl = verify_ssl

    def build_client(self) -> None:
        """
        Construct the ProxmoxAPI client.

        Allows inserting the realm within the `user` value.
        """
        user_id = self._user if "@" in self._user else f"{self._user}@{self._realm}"

        if self._token_name:
            self._proxmox = ProxmoxAPI(
                self._host,
                port=self._port,
                user=user_id,
                token_name=self._token_name,
                token_value=self._password,
                verify_ssl=self._verify_ssl,
                timeout=30,
            )
        else:
            self._proxmox = ProxmoxAPI(
                self._host,
                port=self._port,
                user=user_id,
                password=self._password,
                verify_ssl=self._verify_ssl,
                timeout=30,
            )

        # One coordinator per node/QEMU/LXC/disk means many refreshes fire at
        # the same time. With pool_block=False urllib3 opens extra connections
        # beyond pool_maxsize and discards them on release, logging
        # "Connection pool is full, discarding connection" each time. Blocking
        # instead caps the concurrent connections at pool_maxsize and makes the
        # surplus requests wait for a free one - no churn, no warning.
        adapter = HTTPAdapter(
            pool_connections=32,
            pool_maxsize=32,
            max_retries=0,
            pool_block=True,
        )

        # proxmoxer exposes no public accessor for the underlying requests session.
        session = self._proxmox._store["session"]  # noqa: SLF001
        session.mount("https://", adapter)

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


def put_api(
    proxmox: ProxmoxAPI,
    api_path: str,
    **kwargs: Any,
) -> dict[str, Any] | None:
    """Put data to Proxmox API."""
    api_result = proxmox.put(api_path, **kwargs)
    LOGGER.debug("API PUT - %s: %s", api_path, api_result)
    return api_result


def post_api_command(
    self,
    *,
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
        msg = "Invalid Command"
        raise ValueError(msg)

    if api_category is ProxmoxType.Proxmox:
        issue_id = f"{self.config_entry.entry_id}_cluster_command_forbiden"
    elif api_category is ProxmoxType.Node:
        issue_id = f"{self.config_entry.entry_id}_{node}_command_forbiden"
    elif api_category in (ProxmoxType.QEMU, ProxmoxType.LXC):
        issue_id = f"{self.config_entry.entry_id}_{vm_id}_command_forbiden"

    try:
        if api_category is ProxmoxType.Proxmox:
            # Cluster-wide HA arm/disarm; not tied to a node or guest.
            # Mounted under PVE::API2::HA::Status, i.e. cluster/ha/status/...,
            # not directly under cluster/ha/.
            # disarm-ha requires resource-mode (freeze|ignore); default to
            # the safer "freeze" (HA services are locked in their current
            # state, no automatic action) rather than "ignore" (HA tracking
            # is fully suspended, allowing manual guest management during
            # the disarmed window).
            if command == ProxmoxCommand.DISARM_HA:
                result = post_api(
                    proxmox, f"cluster/ha/status/{command}?resource-mode=freeze"
                )
            else:
                result = post_api(proxmox, f"cluster/ha/status/{command}")
        # START_ALL, STOP_ALL, WAKEONLAN are not part of status API
        elif api_category is ProxmoxType.Node and command in [
            ProxmoxCommand.START_ALL,
            ProxmoxCommand.STOP_ALL,
            ProxmoxCommand.WAKEONLAN,
        ]:
            result = post_api(proxmox, f"nodes/{node}/{command}")
        elif api_category is ProxmoxType.Node:
            result = post_api(proxmox, f"nodes/{node}/status?command={command}")
        elif command == ProxmoxCommand.HIBERNATE:
            result = post_api(
                proxmox,
                f"nodes/{node}/{api_category}/{vm_id}/status/{ProxmoxCommand.SUSPEND}?todisk=1",
            )
        elif command == ProxmoxCommand.UNLOCK:
            # Unlock is not part of the status API; it removes the config
            # lock (equivalent to `pct unlock` / `qm unlock`). QEMU refuses to
            # edit a locked guest's config unless skiplock=1 is passed (allowed
            # for root@pam only); the LXC config endpoint has no skiplock
            # parameter and rejects it, so it is sent for QEMU only.
            extra = {"skiplock": 1} if api_category is ProxmoxType.QEMU else {}
            result = put_api(
                proxmox,
                f"nodes/{node}/{api_category}/{vm_id}/config",
                delete="lock",
                **extra,
            )
        else:
            result = post_api(
                proxmox, f"nodes/{node}/{api_category}/{vm_id}/status/{command}"
            )

    except ResourceException as error:
        if api_category is ProxmoxType.Proxmox:
            resource = "Cluster HA"
        elif api_category is ProxmoxType.Node:
            resource = f"{api_category.capitalize()} {node}"
        else:
            resource = f"{api_category.upper()} {vm_id}"
        if error.status_code == 403:
            permissions = str(error).split("(")[1].split(",")
            permission_check = (
                f"['perm','{permissions[0]}',[{permissions[1].strip().strip(')')}]]"
            )
            ir.create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="resource_command_forbiden",
                translation_placeholders={
                    "resource": resource,
                    "user": (
                        self.config_entry.data.get(CONF_HA_ADMIN_USERNAME)
                        if api_category is ProxmoxType.Proxmox
                        else self.config_entry.data[CONF_USERNAME]
                    ),
                    "permission": permission_check,
                    "command": command,
                },
            )
        # Surface every API error (e.g. a still-present lock, or skiplock
        # being rejected for a non-root user) instead of silently swallowing
        # non-403 responses, which made failed commands look successful.
        msg = f"Proxmox {resource} {command} error - {error}"
        raise HomeAssistantError(
            msg,
        ) from error

    except ConnectTimeout as error:
        msg = f"Proxmox {resource} {command} error - {error}"
        raise HomeAssistantError(
            msg,
        ) from error

    ir.delete_issue(
        self.hass,
        DOMAIN,
        issue_id,
    )

    return result
