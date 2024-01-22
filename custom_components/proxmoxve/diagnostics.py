"""Support for the Airzone diagnostics."""
from __future__ import annotations

from collections.abc import Mapping
import datetime
from typing import Any

from attr import asdict
from proxmoxer.core import ResourceException

from homeassistant.components.diagnostics.util import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntry

from .api import get_api
from .const import CONF_DISKS_ENABLE, COORDINATORS, DOMAIN, PROXMOX_CLIENT
from .coordinator import (
    ProxmoxDiskCoordinator,
    ProxmoxLXCCoordinator,
    ProxmoxNodeCoordinator,
    ProxmoxQEMUCoordinator,
    ProxmoxStorageCoordinator,
    ProxmoxUpdateCoordinator,
)

TO_REDACT_CONFIG = ["host", "username", "password"]

TO_REDACT_COORD = [""]

TO_REDACT_API = [""]

TO_REDACT_DATA = ["configuration_url"]


async def async_get_api_data_diagnostics(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> dict[str, Any]:
    """Get API info for diagnostics."""

    proxmox_client = hass.data[DOMAIN][config_entry.entry_id][PROXMOX_CLIENT]

    proxmox = proxmox_client.get_api_client()

    try:
        resources = await hass.async_add_executor_job(
            get_api, proxmox, "cluster/resources"
        )
    except ResourceException as error:
        if error.status_code == 403:
            resources["error"] = "403 Forbidden: Permission check failed"
        else:
            resources["error"] = error

    nodes = {}
    try:
        nodes_api = await hass.async_add_executor_job(get_api, proxmox, "nodes")
    except ResourceException as error:
        if error.status_code == 403:
            nodes_api["error"] = "403 Forbidden: Permission check failed"
        else:
            nodes_api["error"] = error

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
                    nodes[node["node"]]["qemu"][qemu["vmid"]]["backups"] = error
        except ResourceException as error:
            if error.status_code == 403:
                nodes[node["node"]]["qemu"][
                    "error"
                ] = "403 Forbidden: Permission check failed"
            else:
                nodes[node["node"]]["qemu"]["error"] = error

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
                    nodes[node["node"]]["lxc"][lxc["vmid"]]["backups"]["error"] = error
        except ResourceException as error:
            if error.status_code == 403:
                nodes[node["node"]]["lxc"][
                    "error"
                ] = "403 Forbidden: Permission check failed"
            else:
                nodes[node["node"]]["lxc"]["error"] = error

        try:
            nodes[node["node"]]["storage"] = await hass.async_add_executor_job(
                get_api, proxmox, f"nodes/{node['node']}/storage"
            )
        except ResourceException as error:
            if error.status_code == 403:
                nodes[node["node"]]["storage"][
                    "error"
                ] = "403 Forbidden: Permission check failed"
            else:
                nodes[node["node"]]["storage"]["error"] = error

        try:
            nodes[node["node"]]["updates"] = await hass.async_add_executor_job(
                get_api, proxmox, f"nodes/{node['node']}/apt/update"
            )
        except ResourceException as error:
            if error.status_code == 403:
                nodes[node["node"]]["updates"][
                    "error"
                ] = "403 Forbidden: Permission check failed"
            else:
                nodes[node["node"]]["updates"]["error"] = error

        try:
            nodes[node["node"]]["versions"] = await hass.async_add_executor_job(
                get_api, proxmox, f"nodes/{node['node']}/apt/versions"
            )
        except ResourceException as error:
            nodes[node["node"]]["updates"]["error"] = error

        if config_entry.options.get(CONF_DISKS_ENABLE, True):
            try:
                disks = await hass.async_add_executor_job(
                    get_api, proxmox, f"nodes/{node['node']}/disks/list"
                )

                nodes[node["node"]]["disks"] = {}
                for disk in disks if disks is not None else []:
                    try:
                        disk_attributes = await hass.async_add_executor_job(
                            get_api,
                            proxmox,
                            f"nodes/{node['node']}/disks/smart/?disk={disk['devpath']}",
                        )
                    except:
                        disk_attributes = None

                    nodes[node["node"]]["disks"][disk["devpath"]] = {
                        "data": disk,
                        "smart": disk_attributes,
                    }

            except ResourceException as error:
                if error.status_code == 403:
                    nodes[node["node"]]["disks"][
                        "error"
                    ] = "403 Forbidden: Permission check failed"
                else:
                    nodes[node["node"]]["disks"]["error"] = error
        else:
            nodes[node["node"]]["disks"][
                "info"
            ] = "Disk information disabled in integration configuration options"

    return {
        "resources": resources,
        "nodes": nodes,
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""

    coordinators: dict[
        str,
        ProxmoxNodeCoordinator
        | ProxmoxQEMUCoordinator
        | ProxmoxLXCCoordinator
        | ProxmoxStorageCoordinator
        | ProxmoxUpdateCoordinator
        | ProxmoxDiskCoordinator,
    ] = hass.data[DOMAIN][config_entry.entry_id][COORDINATORS]

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

            entities.append({"entry": asdict(entity_entry), "state": state_dict})

        devices.append({"device": asdict(device), "entities": entities})

    proxmox_coordinators = {}
    for coordinator_name, coordinator in coordinators.items():
        if (
            type(coordinator)
            in (
                ProxmoxNodeCoordinator,
                ProxmoxQEMUCoordinator,
                ProxmoxLXCCoordinator,
                ProxmoxStorageCoordinator,
                ProxmoxUpdateCoordinator,
                ProxmoxDiskCoordinator,
            )
            and (coordinator_data := coordinator.data) is not None
        ):
            proxmox_coordinators[coordinator_name] = coordinator_data.__dict__
        elif isinstance(coordinator, list):
            for coordinator_sub in coordinator:
                if (
                    type(coordinator_sub)
                    in (
                        ProxmoxNodeCoordinator,
                        ProxmoxQEMUCoordinator,
                        ProxmoxLXCCoordinator,
                        ProxmoxStorageCoordinator,
                        ProxmoxUpdateCoordinator,
                        ProxmoxDiskCoordinator,
                    )
                    and (coordinator_sub_data := coordinator_sub.data) is not None
                ):
                    proxmox_coordinators[
                        coordinator_sub.name
                    ] = coordinator_sub_data.__dict__

    return {
        "timestamp": datetime.datetime.now(),
        "config_entry": async_redact_data(config_entry.data, TO_REDACT_CONFIG),
        "options": async_redact_data(config_entry.options, TO_REDACT_CONFIG),
        "devices": async_redact_data(devices, TO_REDACT_DATA),
        "proxmox_coordinators": async_redact_data(
            proxmox_coordinators, TO_REDACT_COORD
        ),
        "api_response": async_redact_data(api_data, TO_REDACT_API)
        if api_data is not None
        else {},
    }


async def async_get_device_diagnostics(
    hass: HomeAssistant, config_entry: ConfigEntry, device: DeviceEntry
) -> Mapping[str, Any]:
    """Return diagnostics for a device entry."""

    config_entry_diagnostics = await async_get_config_entry_diagnostics(
        hass, config_entry
    )

    return {
        "source": f"device - {device.id}",
        **config_entry_diagnostics,
    }
