# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Handle API for Proxmox VE."""

import re
import threading
from collections.abc import Iterable
from typing import Any

import homeassistant.util.dt as dt_util
from homeassistant.const import CONF_USERNAME
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from proxmoxer import AuthenticationError, ProxmoxAPI
from proxmoxer.backends.https import ProxmoxHTTPAuth
from proxmoxer.core import ResourceException
from requests.adapters import HTTPAdapter
from requests.exceptions import ConnectTimeout, RequestException

from .const import (
    CONF_BACKUP_STORAGE,
    CONF_HA_ADMIN_USERNAME,
    DEFAULT_PORT,
    DEFAULT_REALM,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    LOGGER,
    ProxmoxCommand,
    ProxmoxType,
)

AUTH_STATUS_PATTERN = re.compile(r"code: (\d+)")
API_TIMEOUT = 30


def auth_error_status(error: BaseException) -> int | None:
    """
    Return the HTTP status behind a proxmoxer AuthenticationError, if it says.

    proxmoxer raises the same exception for a wrong password (401) and for a
    host whose API is up but not ready to issue tickets yet (500, 595, ...).
    Only the first is a reason to ask for new credentials.
    """
    match = AUTH_STATUS_PATTERN.search(str(error))
    return int(match.group(1)) if match else None


def token_name_only(value: str | None) -> str:
    """
    Reduce whatever was typed into the token field to the token's name.

    Proxmox shows a token as `user@realm!name`, and that is what people copy
    into the field - the login then fails with "no such user
    ('user@realm!user@realm')", because the user and realm get prepended a
    second time. A token name itself can never contain `!`, so everything up
    to the last one is not part of it.
    """
    if not value:
        return ""
    return value.strip().rsplit("!", 1)[-1].strip()


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
        # The configured host first, then whatever the cluster says its other
        # nodes answer on. Only the first is ever written anywhere.
        self._hosts: list[str] = [host]
        self._host_index = 0
        # Every API object this client ever built. A coordinator that was
        # handed one of them asks for the current one by showing what it has.
        self._issued: list[ProxmoxAPI] = []
        # Bumped on every host change, so a poll that failed against the old
        # host can tell whether another poll already moved on.
        self.generation = 0
        self._switch_lock = threading.Lock()

    @property
    def host(self) -> str:
        """Return the host currently in use."""
        return self._hosts[self._host_index]

    @property
    def hosts(self) -> tuple[str, ...]:
        """Return every host this client may use, the configured one first."""
        return tuple(self._hosts)

    def build_client(self) -> None:
        """Construct the ProxmoxAPI client against the current host."""
        self._proxmox = self._build(self.host)

    def _build(self, host: str) -> ProxmoxAPI:
        """
        Construct a ProxmoxAPI client for one host.

        Allows inserting the realm within the `user` value.
        """
        user_id = self._user_id()

        if token_name := token_name_only(self._token_name):
            proxmox = ProxmoxAPI(
                host,
                port=self._port,
                user=user_id,
                token_name=token_name,
                token_value=self._password,
                verify_ssl=self._verify_ssl,
                timeout=API_TIMEOUT,
            )
        else:
            proxmox = ProxmoxAPI(
                host,
                port=self._port,
                user=user_id,
                password=self._password,
                verify_ssl=self._verify_ssl,
                timeout=API_TIMEOUT,
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
        session = proxmox._store["session"]  # noqa: SLF001
        session.mount("https://", adapter)
        self._issued.append(proxmox)
        return proxmox

    def get_api_client(self) -> ProxmoxAPI:
        """Return the ProxmoxAPI client."""
        return self._proxmox

    def issued(self, proxmox: ProxmoxAPI) -> bool:
        """Return whether `proxmox` is one of the API objects this client built."""
        return any(candidate is proxmox for candidate in self._issued)

    def learn_hosts(self, hosts: Iterable[str]) -> None:
        """
        Remember the other nodes of the cluster as places to fall back to.

        `cluster/status` says what address every node answers on. That is the
        corosync address, which on a cluster with a separate cluster network
        is not reachable from Home Assistant at all - so these are tried, not
        relied on. The configured host stays first.
        """
        for host in hosts:
            if isinstance(host, str) and host and host not in self._hosts:
                self._hosts.append(host)

    def failover(self, generation: int) -> bool:
        """
        Move to the next node that answers, once the current one stopped.

        Every coordinator polls on its own, so several may hit the dead host
        at once; the first one through switches and the rest see the changed
        generation and simply retry. A candidate has to answer `version` -
        the one call every credential may make - before it counts, since a
        token client is built without touching the network.

        Returns True when a working host is in place (this call's or an
        earlier one's), False when none of them answered.
        """
        with self._switch_lock:
            if generation != self.generation:
                return True
            if len(self._hosts) < 2:
                return False
            for offset in range(1, len(self._hosts)):
                index = (self._host_index + offset) % len(self._hosts)
                host = self._hosts[index]
                try:
                    proxmox = self._build(host)
                    proxmox.version.get()
                except (AuthenticationError, RequestException) as error:
                    LOGGER.debug("Fallback host %s did not answer: %s", host, error)
                    continue
                LOGGER.warning(
                    "Proxmox at %s stopped answering; using %s until it is back",
                    self.host,
                    host,
                )
                self._host_index = index
                self._proxmox = proxmox
                self.generation += 1
                return True
            return False

    def relogin(self) -> bool:
        """
        Log in again with the stored password, keeping every reference valid.

        proxmoxer does not keep the password. It renews the ticket with the
        ticket itself, and a ticket is valid for two hours - so once the host
        has been unreachable for longer than that, the next renewal is
        refused with 401, exactly as a wrong password would be, and the
        session can never recover on its own. This performs the login the
        way the backend does at construction and swaps the result in, so the
        coordinators holding the client see the new ticket.

        Returns False for token authentication, which has nothing to renew.
        Raises AuthenticationError when the password really is wrong.
        """
        if self._token_name:
            return False
        backend = self._proxmox._backend  # noqa: SLF001
        auth = ProxmoxHTTPAuth(
            self._user_id(),
            self._password,
            base_url=backend.get_base_url(),
            verify_ssl=self._verify_ssl,
            timeout=API_TIMEOUT,
        )
        backend.auth = auth
        self._proxmox._store["session"].auth = auth  # noqa: SLF001
        return True

    def _user_id(self) -> str:
        """Return the user with its realm, as Proxmox wants it."""
        return self._user if "@" in self._user else f"{self._user}@{self._realm}"


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
    **kwargs: Any,
) -> dict[str, Any] | None:
    """Post data to Proxmox API."""
    api_result = proxmox.post(api_path, **kwargs)
    LOGGER.debug("API POST - %s %s: %s", api_path, kwargs or "", api_result)
    return api_result


# Proxmox accepts a snapshot name matching `[a-zA-Z][a-zA-Z0-9_-]+`, at most
# 40 characters. This prefix plus a local timestamp comes to 29, and a local
# timestamp is what reads naturally next to the snapshot list in the web
# interface, which shows the creation time in local time as well.
SNAPSHOT_NAME_PREFIX = "homeassistant_"
SNAPSHOT_NAME_MAX_LENGTH = 40


def snapshot_name() -> str:
    """Return a snapshot name for right now that the API accepts."""
    name = f"{SNAPSHOT_NAME_PREFIX}{dt_util.now().strftime('%Y%m%d_%H%M%S')}"
    return name[:SNAPSHOT_NAME_MAX_LENGTH]


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
        # START_ALL, STOP_ALL, SUSPEND_ALL, WAKEONLAN are not part of status API
        elif command in (ProxmoxCommand.BACKUP, ProxmoxCommand.BACKUP_ALL):
            # One vzdump run, in snapshot mode, to the storage picked in the
            # options; the button exists only while one is picked. The task
            # shows up where the backup sensors already look.
            storage = self.config_entry.options.get(CONF_BACKUP_STORAGE)
            target = (
                {"all": 1} if command == ProxmoxCommand.BACKUP_ALL else {"vmid": vm_id}
            )
            result = post_api(
                proxmox,
                f"nodes/{node}/vzdump",
                mode="snapshot",
                storage=storage,
                **target,
            )
        elif api_category is ProxmoxType.Node and command in [
            ProxmoxCommand.START_ALL,
            ProxmoxCommand.STOP_ALL,
            ProxmoxCommand.SUSPEND_ALL,
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
        elif command == ProxmoxCommand.SNAPSHOT:
            # Not part of the status API either. Without `vmstate` a VM
            # snapshot captures the disks only, which is the quick, safe
            # default; the description says where it came from when it
            # turns up in the snapshot list months later.
            result = post_api(
                proxmox,
                f"nodes/{node}/{api_category}/{vm_id}/snapshot",
                snapname=snapshot_name(),
                description="Created by Home Assistant",
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
