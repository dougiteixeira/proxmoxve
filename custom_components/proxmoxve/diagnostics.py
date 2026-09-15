# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Diagnostics support for Proxmox VE."""

from __future__ import annotations

import dataclasses
import datetime
from typing import TYPE_CHECKING, Any

from attr import Attribute, asdict
from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import UNDEFINED
from proxmoxer.core import ResourceException

from .api import get_api
from .const import (
    CONF_DISKS_ENABLE,
    CONF_HA_ADMIN_PASSWORD,
    CONF_HA_ADMIN_USERNAME,
    COORDINATORS,
    PROXMOX_CLIENT,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

TO_REDACT_CONFIG = {
    CONF_HOST,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_HA_ADMIN_USERNAME,
    CONF_HA_ADMIN_PASSWORD,
}
TO_REDACT_COORD: set[str] = set()
TO_REDACT_API: set[str] = set()
TO_REDACT_DATA = {"configuration_url"}


def _exclude_registry_cache(attribute: Attribute, _value: Any) -> bool:
    """
    Drop the registry entries' internal `_cache` field.

    It holds a pre-serialized storage/json representation of the whole
    entry (e.g. `configuration_url` with the real host), which bypasses
    key-based redaction since it's embedded as a plain string.
    """
    return attribute.name != "_cache"


def _error_info(error: ResourceException) -> dict[str, str]:
    """Turn a ResourceException into a JSON-serializable error dict."""
    if error.status_code == 403:
        return {"error": "403 Forbidden: Permission check failed"}
    return {"error": str(error)}


async def async_get_api_data_diagnostics(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> dict[str, Any]:
    """Get API info for diagnostics."""
    proxmox_client = config_entry.runtime_data[PROXMOX_CLIENT]

    proxmox = proxmox_client.get_api_client()

    resources: dict[str, Any] = {}
    try:
        resources = await hass.async_add_executor_job(
            get_api, proxmox, "cluster/resources"
        )
    except ResourceException as error:
        resources = _error_info(error)

    nodes: dict[str, Any] = {}
    nodes_api = None
    try:
        nodes_api = await hass.async_add_executor_job(get_api, proxmox, "nodes")
    except ResourceException as error:
        nodes["error"] = _error_info(error)["error"]

    for node in nodes_api if nodes_api is not None else []:
        nodes[node["node"]] = node

        try:
            nodes[node["node"]]["qemu"] = {}
            qemu_node = await hass.async_add_executor_job(
                get_api, proxmox, f"nodes/{node['node']}/qemu"
            )
            for qemu in qemu_node if qemu_node is not None else []:
                nodes[node["node"]]["qemu"][qemu["vmid"]] = qemu
                try:
                    nodes[node["node"]]["qemu"][qemu["vmid"]][
                        "backups"
                    ] = await hass.async_add_executor_job(
                        get_api,
                        proxmox,
                        f"nodes/{node['node']}/qemu/{qemu['vmid']}/snapshot",
                    )
                except ResourceException as error:
                    nodes[node["node"]]["qemu"][qemu["vmid"]]["backups"] = _error_info(
                        error
                    )
        except ResourceException as error:
            nodes[node["node"]]["qemu"] = _error_info(error)

        try:
            nodes[node["node"]]["lxc"] = {}
            lxc_node = await hass.async_add_executor_job(
                get_api, proxmox, f"nodes/{node['node']}/lxc"
            )
            for lxc in lxc_node if lxc_node is not None else []:
                nodes[node["node"]]["lxc"][lxc["vmid"]] = lxc
                try:
                    nodes[node["node"]]["lxc"][lxc["vmid"]][
                        "backups"
                    ] = await hass.async_add_executor_job(
                        get_api,
                        proxmox,
                        f"nodes/{node['node']}/lxc/{lxc['vmid']}/snapshot",
                    )
                except ResourceException as error:
                    nodes[node["node"]]["lxc"][lxc["vmid"]]["backups"] = _error_info(
                        error
                    )
        except ResourceException as error:
            nodes[node["node"]]["lxc"] = _error_info(error)

        try:
            nodes[node["node"]]["storage"] = await hass.async_add_executor_job(
                get_api, proxmox, f"nodes/{node['node']}/storage"
            )
        except ResourceException as error:
            nodes[node["node"]]["storage"] = _error_info(error)

        try:
            nodes[node["node"]]["zfs"] = await hass.async_add_executor_job(
                get_api, proxmox, f"nodes/{node['node']}/disks/zfs"
            )
        except ResourceException as error:
            nodes[node["node"]]["zfs"] = _error_info(error)

        try:
            nodes[node["node"]]["updates"] = await hass.async_add_executor_job(
                get_api, proxmox, f"nodes/{node['node']}/apt/update"
            )
        except ResourceException as error:
            nodes[node["node"]]["updates"] = _error_info(error)

        try:
            nodes[node["node"]]["versions"] = await hass.async_add_executor_job(
                get_api, proxmox, f"nodes/{node['node']}/apt/versions"
            )
        except ResourceException as error:
            nodes[node["node"]]["versions"] = _error_info(error)

        nodes[node["node"]]["disks"] = {}
        if config_entry.options.get(CONF_DISKS_ENABLE, True):
            try:
                disks = await hass.async_add_executor_job(
                    get_api, proxmox, f"nodes/{node['node']}/disks/list"
                )

                for disk in disks if disks is not None else []:
                    try:
                        disk_attributes = await hass.async_add_executor_job(
                            get_api,
                            proxmox,
                            f"nodes/{node['node']}/disks/smart/?disk={disk['devpath']}",
                        )
                    except ResourceException:
                        disk_attributes = None

                    nodes[node["node"]]["disks"][disk["devpath"]] = {
                        "data": disk,
                        "smart": disk_attributes,
                    }

            except ResourceException as error:
                nodes[node["node"]]["disks"] = _error_info(error)
        else:
            nodes[node["node"]]["disks"]["info"] = (
                "Disk information disabled in integration configuration options"
            )

    return {
        "resources": resources,
        "nodes": nodes,
    }


def _coordinator_snapshot(data: Any) -> Any:
    """
    Return a JSON-serializable snapshot of a coordinator's last data.

    Walks dataclasses by hand (rather than `dataclasses.asdict`, which
    deep-copies every field) so the `is UNDEFINED` identity check below is
    reliable, and turns the UNDEFINED sentinel into a readable string
    instead of failing the JSON dump.
    """
    if data is UNDEFINED:
        return "undefined"
    if dataclasses.is_dataclass(data) and not isinstance(data, type):
        return {
            field.name: _coordinator_snapshot(getattr(data, field.name))
            for field in dataclasses.fields(data)
        }
    if isinstance(data, dict):
        return {key: _coordinator_snapshot(value) for key, value in data.items()}
    if isinstance(data, set):
        return sorted(_coordinator_snapshot(value) for value in data)
    if isinstance(data, (list, tuple)):
        return [_coordinator_snapshot(value) for value in data]
    return data


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinators = config_entry.runtime_data[COORDINATORS]

    api_data = await async_get_api_data_diagnostics(hass, config_entry)

    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)

    devices = []

    registry_devices = dr.async_entries_for_config_entry(
        device_registry, config_entry.entry_id
    )

    for device in registry_devices:
        entities = []

        registry_entities = er.async_entries_for_device(
            entity_registry,
            device_id=device.id,
            include_disabled_entities=True,
        )

        for entity_entry in registry_entities:
            state_dict = None
            if state := hass.states.get(entity_entry.entity_id):
                state_dict = dict(state.as_dict())
                state_dict.pop("context", None)

            entities.append(
                {
                    "entry": asdict(entity_entry, filter=_exclude_registry_cache),
                    "state": state_dict,
                }
            )

        devices.append(
            {
                "device": asdict(device, filter=_exclude_registry_cache),
                "entities": entities,
            }
        )

    proxmox_coordinators: dict[str, Any] = {}
    for coordinator_name, coordinator in coordinators.items():
        if isinstance(coordinator, list):
            proxmox_coordinators[coordinator_name] = [
                _coordinator_snapshot(sub_coordinator.data)
                for sub_coordinator in coordinator
                if sub_coordinator.data is not None
            ]
        elif coordinator.data is not None:
            proxmox_coordinators[coordinator_name] = _coordinator_snapshot(
                coordinator.data
            )

    return {
        "timestamp": datetime.datetime.now(datetime.UTC),
        "config_entry": async_redact_data(config_entry.data, TO_REDACT_CONFIG),
        "options": async_redact_data(config_entry.options, TO_REDACT_CONFIG),
        "devices": async_redact_data(devices, TO_REDACT_DATA),
        "proxmox_coordinators": async_redact_data(
            proxmox_coordinators, TO_REDACT_COORD
        ),
        "api_response": async_redact_data(api_data, TO_REDACT_API),
    }
