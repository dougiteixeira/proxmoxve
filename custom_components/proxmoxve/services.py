# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""
Actions the integration offers beyond its buttons.

`proxmoxve.backup` starts `vzdump` runs the way the Proxmox interface's
Backup Now does: one API call per node, the node does the rest, and the
run shows up in the task log where the backup sensors already look. What
to back up is said the Home Assistant way - the guest, node or cluster
devices as the target - or by naming a node and guest ids; the node a
guest lives on is looked up, so a call can span the cluster.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.const import (
    ATTR_AREA_ID,
    ATTR_DEVICE_ID,
    ATTR_ENTITY_ID,
    ATTR_FLOOR_ID,
    ATTR_LABEL_ID,
)
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from proxmoxer import AuthenticationError
from proxmoxer.core import ResourceException
from requests.exceptions import RequestException

from .api import post_api
from .const import (
    CONF_BACKUP_STORAGE,
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
ATTR_SKIP_IF_RUNNING = "skip_if_running"

BACKUP_MODES = ("snapshot", "suspend", "stop")
BACKUP_COMPRESSION = ("zstd", "gzip", "lzo", "0")

BACKUP_SCHEMA = vol.Schema(
    {
        **cv.TARGET_SERVICE_FIELDS,
        vol.Optional(ATTR_NODE): cv.string,
        vol.Optional(ATTR_VMID): vol.All(cv.ensure_list, [cv.positive_int]),
        vol.Optional(ATTR_ALL, default=False): cv.boolean,
        vol.Optional(ATTR_STORAGE): cv.string,
        vol.Optional(ATTR_MODE, default="snapshot"): vol.In(BACKUP_MODES),
        vol.Optional(ATTR_COMPRESS): vol.In(BACKUP_COMPRESSION),
        vol.Optional(ATTR_NOTES): cv.string,
        vol.Optional(ATTR_SKIP_IF_RUNNING, default=False): cv.boolean,
    }
)

# The device identifiers `device_info` builds: `<entry>_cluster`,
# `<entry>_NODE_<node>`, `<entry>_QEMU_<vmid>`, `<entry>_LXC_<vmid>`.
CLUSTER_IDENTIFIER = "cluster"
GUEST_KINDS = (ProxmoxType.QEMU.upper(), ProxmoxType.LXC.upper())


@dataclasses.dataclass
class BackupPlan:
    """One `vzdump` run: a node, and the guests on it or everything it hosts."""

    entry: ConfigEntry
    node: str
    vmids: set[int] = dataclasses.field(default_factory=set)
    everything: bool = False

    def add(self, vmid: int | None) -> None:
        """Add a guest, or with `None` everything the node hosts."""
        if vmid is None:
            self.everything = True
        else:
            self.vmids.add(vmid)


def loaded_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    """Return the entries that are set up, in configuration order."""
    return [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if isinstance(getattr(entry, "runtime_data", None), dict)
    ]


def entry_tracking_node(hass: HomeAssistant, node: str) -> ConfigEntry | None:
    """Return the loaded entry that tracks `node`, if any does."""
    for entry in loaded_entries(hass):
        if node in entry.runtime_data.get(TRACKED, {}).get(CONF_NODES, []):
            return entry
    return None


def entry_hosting_guest(
    hass: HomeAssistant, vmid: int
) -> tuple[ConfigEntry, str] | None:
    """Return the entry tracking guest `vmid` and the node it lives on."""
    for entry in loaded_entries(hass):
        coordinators = entry.runtime_data.get(COORDINATORS, {})
        for kind in (ProxmoxType.QEMU, ProxmoxType.LXC):
            coordinator = coordinators.get(f"{kind}_{vmid}")
            if coordinator is not None and coordinator.data is not None:
                return entry, coordinator.data.node
    return None


def tracked_nodes(entry: ConfigEntry) -> list[str]:
    """Return the nodes the entry tracks."""
    return list(entry.runtime_data.get(TRACKED, {}).get(CONF_NODES, []))


def _not_a_backup_target(device: dr.DeviceEntry) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="backup_target_not_supported",
        translation_placeholders={"device": device.name_by_user or device.name or ""},
    )


def resolve_device(
    hass: HomeAssistant, device_id: str
) -> list[tuple[ConfigEntry, str, int | None]]:
    """
    Turn a targeted device into (entry, node, vmid) triples.

    A guest device is itself; a node device is everything on that node;
    the cluster device is everything on every node of its entry. Storage
    and disk devices cannot be backed up and say so.
    """
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="backup_target_unknown",
            translation_placeholders={"device": device_id},
        )
    entries = {entry.entry_id: entry for entry in loaded_entries(hass)}
    for domain, identifier in device.identifiers:
        if domain != DOMAIN:
            continue
        entry_id, _, rest = identifier.partition("_")
        if (entry := entries.get(entry_id)) is None:
            continue
        if rest == CLUSTER_IDENTIFIER:
            return [(entry, node, None) for node in tracked_nodes(entry)]
        kind, _, resource = rest.partition("_")
        if kind == ProxmoxType.Node.upper():
            return [(entry, resource, None)]
        if kind in GUEST_KINDS and resource.isdigit():
            vmid = int(resource)
            if (hosting := entry_hosting_guest(hass, vmid)) is not None:
                return [(hosting[0], hosting[1], vmid)]
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="backup_unknown_guest",
                translation_placeholders={"vmid": str(vmid)},
            )
        raise _not_a_backup_target(device)
    raise _not_a_backup_target(device)


def _ids(call_data: dict[str, Any], key: str) -> list[str]:
    """Return the ids under a target key; `none`/`all` are not ids."""
    value = call_data.get(key)
    if not value or value in ("none", "all"):
        return []
    return list(cv.ensure_list(value))


def targeted_devices(hass: HomeAssistant, call_data: dict[str, Any]) -> list[str]:
    """
    Return the device ids the call targets, in the order given.

    Devices count as themselves, entities by their device, areas and
    labels by the devices and entities in them, floors by their areas.
    """
    devices = dr.async_get(hass)
    entities = er.async_get(hass)
    areas = ar.async_get(hass)
    found: list[str] = []

    def add(device_id: str | None) -> None:
        if device_id and device_id not in found:
            found.append(device_id)

    area_ids = _ids(call_data, ATTR_AREA_ID)
    for floor_id in _ids(call_data, ATTR_FLOOR_ID):
        area_ids.extend(
            area.id for area in areas.async_list_areas() if area.floor_id == floor_id
        )

    for device_id in _ids(call_data, ATTR_DEVICE_ID):
        add(device_id)
    for entity_id in _ids(call_data, ATTR_ENTITY_ID):
        if (entity := entities.async_get(entity_id)) is not None:
            add(entity.device_id)
    for area_id in area_ids:
        for device in dr.async_entries_for_area(devices, area_id):
            add(device.id)
        for entity in er.async_entries_for_area(entities, area_id):
            add(entity.device_id)
    for label_id in _ids(call_data, ATTR_LABEL_ID):
        for device in dr.async_entries_for_label(devices, label_id):
            add(device.id)
        for entity in er.async_entries_for_label(entities, label_id):
            add(entity.device_id)
    return found


def plan_backups(
    hass: HomeAssistant, call_data: dict[str, Any], devices: list[str]
) -> list[BackupPlan]:
    """
    Work out which nodes run what, from the targets and the named fields.

    Targets and `vmid` are looked up to the node they live on; `node`
    names one outright, `all` on its own means every node tracked. Naming
    nothing is a mistake, not a backup of nothing.
    """
    plans: dict[tuple[str, str], BackupPlan] = {}

    def add(entry: ConfigEntry, node: str, vmid: int | None) -> None:
        plans.setdefault((entry.entry_id, node), BackupPlan(entry, node)).add(vmid)

    for device_id in devices:
        for entry, node, vmid in resolve_device(hass, device_id):
            add(entry, node, vmid)

    vmids = call_data.get(ATTR_VMID) or []
    everything = bool(call_data.get(ATTR_ALL))
    if node := call_data.get(ATTR_NODE):
        if (entry := entry_tracking_node(hass, node)) is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="backup_unknown_node",
                translation_placeholders={"node": node},
            )
        if everything:
            add(entry, node, None)
        for vmid in vmids:
            add(entry, node, vmid)
    else:
        for vmid in vmids:
            if (hosting := entry_hosting_guest(hass, vmid)) is None:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="backup_unknown_guest",
                    translation_placeholders={"vmid": str(vmid)},
                )
            add(hosting[0], hosting[1], vmid)
        if everything and not devices:
            for entry in loaded_entries(hass):
                for tracked in tracked_nodes(entry):
                    add(entry, tracked, None)

    if not plans:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="backup_nothing_selected"
        )
    return list(plans.values())


def vzdump_parameters(call_data: dict[str, Any], plan: BackupPlan) -> dict[str, Any]:
    """
    Turn one plan into what `nodes/{node}/vzdump` takes.

    The storage falls back to the one picked for the backup buttons in the
    entry's options, so a call - or a blueprint - need not repeat it.
    """
    params: dict[str, Any] = (
        {"all": 1}
        if plan.everything
        else {"vmid": ",".join(str(vmid) for vmid in sorted(plan.vmids))}
    )
    params["mode"] = call_data.get(ATTR_MODE, "snapshot")
    storage = call_data.get(ATTR_STORAGE) or plan.entry.options.get(CONF_BACKUP_STORAGE)
    if storage:
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


def backup_running_on(plan: BackupPlan) -> bool:
    """Return whether the node's backup coordinator sees a run in progress."""
    coordinator = plan.entry.runtime_data[COORDINATORS].get(
        f"{ProxmoxType.Backup}_{plan.node}"
    )
    return bool(
        coordinator is not None and coordinator.data and coordinator.data.running
    )


async def _async_start(
    hass: HomeAssistant, plan: BackupPlan, params: dict[str, Any]
) -> dict[str, Any]:
    """Post one run and hand back what Proxmox made of it."""
    node = plan.node
    proxmox = plan.entry.runtime_data[PROXMOX_CLIENT].get_api_client()
    try:
        upid = await hass.async_add_executor_job(
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
        coordinator := plan.entry.runtime_data[COORDINATORS].get(
            f"{ProxmoxType.Backup}_{node}"
        )
    ) is not None:
        await coordinator.async_request_refresh()
    return {"node": node, "upid": str(upid), **params}


async def _async_backup(call: ServiceCall) -> ServiceResponse:
    """Start the runs and hand back the task ids Proxmox assigns them."""
    devices = targeted_devices(call.hass, dict(call.data))
    plans = plan_backups(call.hass, dict(call.data), devices)
    runs: list[dict[str, Any]] = []
    skipped: list[str] = []
    for plan in plans:
        if call.data.get(ATTR_SKIP_IF_RUNNING) and backup_running_on(plan):
            # vzdump holds one lock per node; a second run would wait for
            # the first, for hours if need be. Skipping is what was asked.
            LOGGER.info("Backup on %s skipped: a run is in progress", plan.node)
            skipped.append(plan.node)
            continue
        params = vzdump_parameters(call.data, plan)
        runs.append(await _async_start(call.hass, plan, params))
    return {"runs": runs, "skipped": skipped}


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
