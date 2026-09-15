# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""
Actions the integration offers beyond its buttons.

`proxmoxve.backup` starts a `vzdump` run on a node - for the guests named
or for everything the node hosts - the way the Proxmox interface's Backup
Now does: one API call, the node does the rest, and the run shows up in
the task log where the backup sensors already look.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from proxmoxer import AuthenticationError
from proxmoxer.core import ResourceException
from requests.exceptions import RequestException

from .api import post_api
from .const import (
    CONF_NODES,
    COORDINATORS,
    DOMAIN,
    LOGGER,
    PROXMOX_CLIENT,
    TRACKED,
    ProxmoxType,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

SERVICE_BACKUP = "backup"
ATTR_NODE = "node"
ATTR_VMID = "vmid"
ATTR_ALL = "all"
ATTR_STORAGE = "storage"
ATTR_MODE = "mode"
ATTR_COMPRESS = "compress"
ATTR_NOTES = "notes"

BACKUP_MODES = ("snapshot", "suspend", "stop")
BACKUP_COMPRESSION = ("zstd", "gzip", "lzo", "0")

BACKUP_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_NODE): cv.string,
        vol.Optional(ATTR_VMID): vol.All(cv.ensure_list, [cv.positive_int]),
        vol.Optional(ATTR_ALL, default=False): cv.boolean,
        vol.Optional(ATTR_STORAGE): cv.string,
        vol.Optional(ATTR_MODE, default="snapshot"): vol.In(BACKUP_MODES),
        vol.Optional(ATTR_COMPRESS): vol.In(BACKUP_COMPRESSION),
        vol.Optional(ATTR_NOTES): cv.string,
    }
)


def entry_tracking_node(hass: HomeAssistant, node: str) -> ConfigEntry | None:
    """Return the loaded entry that tracks `node`, if any does."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        runtime = getattr(entry, "runtime_data", None)
        if not isinstance(runtime, dict):
            continue
        if node in runtime.get(TRACKED, {}).get(CONF_NODES, []):
            return entry
    return None


def vzdump_parameters(call_data: dict[str, Any]) -> dict[str, Any]:
    """
    Turn the call into what `nodes/{node}/vzdump` takes.

    Either the guests named or everything on the node; naming none of the
    guests and not asking for all is a mistake, not a backup of nothing.
    """
    vmids = call_data.get(ATTR_VMID) or []
    if call_data.get(ATTR_ALL):
        params: dict[str, Any] = {"all": 1}
    elif vmids:
        params = {"vmid": ",".join(str(vmid) for vmid in vmids)}
    else:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="backup_nothing_selected"
        )
    params["mode"] = call_data.get(ATTR_MODE, "snapshot")
    if storage := call_data.get(ATTR_STORAGE):
        params["storage"] = storage
    if (compress := call_data.get(ATTR_COMPRESS)) is not None:
        params["compress"] = compress
    if notes := call_data.get(ATTR_NOTES):
        # vzdump accepts a notes template only together with a storage -
        # checked on a live node - and answers a parameter error otherwise.
        if not storage:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="backup_notes_need_storage"
            )
        params["notes-template"] = notes
    return params


async def _async_backup(call: ServiceCall) -> ServiceResponse:
    """Start a backup run and hand back the task id Proxmox assigns it."""
    node = call.data[ATTR_NODE]
    entry = entry_tracking_node(call.hass, node)
    if entry is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="backup_unknown_node",
            translation_placeholders={"node": node},
        )
    params = vzdump_parameters(call.data)
    proxmox = entry.runtime_data[PROXMOX_CLIENT].get_api_client()

    try:
        upid = await call.hass.async_add_executor_job(
            lambda: post_api(proxmox, f"nodes/{node}/vzdump", **params)
        )
    except ResourceException as error:
        # 403 names the missing privilege in its message - VM.Backup on the
        # guest, or Datastore.AllocateSpace on the storage. Pass it on.
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="backup_refused",
            translation_placeholders={"node": node, "error": str(error)},
        ) from error
    except (AuthenticationError, RequestException) as error:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="backup_unreachable",
            translation_placeholders={"node": node, "error": str(error)},
        ) from error

    LOGGER.info("Backup started on %s (%s): %s", node, params, upid)
    # The run is in the task log now; let the node's backup sensors see it.
    if (
        coordinator := entry.runtime_data[COORDINATORS].get(
            f"{ProxmoxType.Backup}_{node}"
        )
    ) is not None:
        await coordinator.async_request_refresh()
    return {"upid": str(upid), "node": node, **params}


def async_register_services(hass: HomeAssistant) -> None:
    """Register the integration's actions, once per Home Assistant."""
    if hass.services.has_service(DOMAIN, SERVICE_BACKUP):
        return
    hass.services.async_register(
        DOMAIN,
        SERVICE_BACKUP,
        _async_backup,
        schema=BACKUP_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
