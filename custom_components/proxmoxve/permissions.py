# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""
What the configured credentials are allowed to do, read once at setup.

`GET /access/permissions` returns the effective privileges of the user or
token making the call, as a mapping of ACL path to the privileges granted
there - `{"/vms/100": {"VM.PowerMgmt": 1, ...}, "/": {...}}`. Privileges
propagate down the tree, so a grant on `/vms` or `/` covers `/vms/100`
unless propagation was switched off for that ACL, which this does not see.

A button for an action the credentials cannot perform is a button that
can only ever fail. Knowing the privileges beforehand lets setup leave
such buttons out rather than have them raise a repair issue on first use.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from proxmoxer import AuthenticationError
from proxmoxer.core import ResourceException
from requests.exceptions import (
    ConnectionError as connError,
)
from requests.exceptions import (
    ConnectTimeout,
    RetryError,
    SSLError,
)

from .api import get_api
from .const import LOGGER

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from proxmoxer import ProxmoxAPI

type Permissions = dict[str, dict[str, int]]


class ProxmoxPrivilege(StrEnum):
    """The Proxmox privileges the buttons need."""

    VM_POWER = "VM.PowerMgmt"
    VM_SNAPSHOT = "VM.Snapshot"
    VM_CONFIG_OPTIONS = "VM.Config.Options"
    SYS_POWER = "Sys.PowerMgmt"
    SYS_CONSOLE = "Sys.Console"


async def async_fetch_permissions(
    hass: HomeAssistant, proxmox: ProxmoxAPI
) -> Permissions | None:
    """
    Read the effective privileges of the credentials behind `proxmox`.

    Returns None when they cannot be read, and the caller then gates
    nothing: not knowing is not the same as not being allowed, and the
    repair issue on a failed command still covers that case.
    """
    try:
        result = await hass.async_add_executor_job(
            get_api, proxmox, "access/permissions"
        )
    except (
        AuthenticationError,
        SSLError,
        ConnectTimeout,
        RetryError,
        connError,
        ResourceException,
    ) as error:
        LOGGER.debug("Could not read the credentials' permissions: %s", error)
        return None

    if not isinstance(result, dict):
        LOGGER.debug("Unexpected answer for access/permissions: %s", type(result))
        return None
    return {
        str(path): {str(name): int(value) for name, value in privileges.items()}
        for path, privileges in result.items()
        if isinstance(privileges, dict)
    }


def is_granted(permissions: Permissions, path: str, privilege: str) -> bool:
    """
    Return whether `privilege` holds at `path`, or at any ACL path above it.

    Walks `/vms/100` -> `/vms` -> `/`, which is how a grant propagates.
    """
    parts = path.strip("/").split("/") if path.strip("/") else []
    candidates = ["/" + "/".join(parts[:depth]) for depth in range(len(parts), 0, -1)]
    candidates.append("/")
    return any(
        permissions.get(candidate, {}).get(privilege) == 1 for candidate in candidates
    )


def is_granted_anywhere_below(
    permissions: Permissions, path: str, privilege: str
) -> bool:
    """
    Return whether `privilege` holds at `path`, above it, or on anything under it.

    For the bulk node actions: `startall` starts every guest the credentials
    may start, so a grant on a single guest is enough for the button to do
    something.
    """
    if is_granted(permissions, path, privilege):
        return True
    prefix = path.rstrip("/") + "/"
    return any(
        privileges.get(privilege) == 1
        for acl_path, privileges in permissions.items()
        if acl_path.startswith(prefix)
    )
