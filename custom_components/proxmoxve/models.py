"""Models for Proxmox VE integration."""

from __future__ import annotations

import dataclasses

from homeassistant.helpers.typing import UndefinedType


@dataclasses.dataclass
class ProxmoxNodeData:
    """Data parsed from the Proxmox API for Node."""

    type: str
    cpu: float
    disk_total: float
    disk_used: float
    model: str
    memory_total: float | UndefinedType
    memory_used: float | UndefinedType
    memory_free: float | UndefinedType
    status: str | UndefinedType
    swap_total: float | UndefinedType
    swap_free: float | UndefinedType
    swap_used: float | UndefinedType
    uptime: int | UndefinedType
    version: str
    qemu_on: int
    qemu_on_list: list
    lxc_on: int
    lxc_on_list: list


@dataclasses.dataclass
class ProxmoxVMData:
    """Data parsed from the Proxmox API for QEMU."""

    type: str
    name: str
    node: str
    cpu: float | UndefinedType
    disk_total: float | UndefinedType
    disk_used: float | UndefinedType
    health: str | UndefinedType
    memory_total: float | UndefinedType
    memory_used: float | UndefinedType
    memory_free: float | UndefinedType
    network_in: float | UndefinedType
    network_out: float | UndefinedType
    status: str | UndefinedType
    uptime: int | UndefinedType


@dataclasses.dataclass
class ProxmoxLXCData:
    """Data parsed from the Proxmox API for LXC."""

    type: str
    name: str
    node: str
    cpu: float | UndefinedType
    disk_total: float | UndefinedType
    disk_used: float | UndefinedType
    memory_total: float | UndefinedType
    memory_used: float | UndefinedType
    memory_free: float | UndefinedType
    network_in: float | UndefinedType
    network_out: float | UndefinedType
    status: str | UndefinedType
    swap_total: float | UndefinedType
    swap_free: float | UndefinedType
    swap_used: float | UndefinedType
    uptime: int | UndefinedType


@dataclasses.dataclass
class ProxmoxStorageData:
    """Data parsed from the Proxmox API for Storage."""

    type: str
    node: str
    name: str
    content: str | UndefinedType
    disk_used: float | UndefinedType
    disk_total: float | UndefinedType


@dataclasses.dataclass
class ProxmoxUpdateData:
    """Data parsed from the Proxmox API for Updates."""

    type: str
    node: str
    updates_list: list | UndefinedType
    total: float | UndefinedType
    update: bool | UndefinedType


@dataclasses.dataclass
class ProxmoxDiskData:
    """Data parsed from the Proxmox API for Disks."""

    type: str
    node: str
    path: str
    serial: str | None
    model: str | None
    vendor: str | None
    disk_type: str | None
    size: float | UndefinedType
    health: str | UndefinedType
    disk_rpm: float | UndefinedType
    temperature: float | UndefinedType
    temperature_air: float | UndefinedType
    power_cycles: int | UndefinedType
    power_hours: int | UndefinedType
    life_left: int | UndefinedType
    power_loss: int | UndefinedType
    disk_wearout: float | UndefinedType
