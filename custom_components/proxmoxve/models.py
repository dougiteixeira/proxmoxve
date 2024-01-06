"""Models for Proxmox VE integration."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from homeassistant.helpers.entity import EntityDescription


@dataclass(frozen=True, kw_only=True)
class ProxmoxEntityDescription(EntityDescription):
    """Describe a Proxmox entity."""


@dataclasses.dataclass
class ProxmoxNodeData:
    """Data parsed from the Proxmox API for Node."""

    type: str
    cpu: float
    disk_total: float
    disk_used: float
    model: str
    memory_total: float
    memory_used: float
    memory_free: float
    status: str
    swap_total: float
    swap_free: float
    swap_used: float
    uptime: int
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
    cpu: float
    disk_total: float
    disk_used: float
    health: str
    memory_total: float
    memory_used: float
    memory_free: float
    network_in: float
    network_out: float
    status: str
    uptime: int


@dataclasses.dataclass
class ProxmoxLXCData:
    """Data parsed from the Proxmox API for LXC."""

    type: str
    name: str
    node: str
    cpu: float
    disk_total: float
    disk_used: float
    memory_total: float
    memory_used: float
    memory_free: float
    network_in: float
    network_out: float
    status: str
    swap_total: float
    swap_free: float
    swap_used: float
    uptime: int


@dataclasses.dataclass
class ProxmoxStorageData:
    """Data parsed from the Proxmox API for Storage."""

    type: str
    node: str
    content: str
    disk_free: float
    disk_used: float
    disk_total: float


@dataclasses.dataclass
class ProxmoxUpdateData:
    """Data parsed from the Proxmox API for Updates."""

    type: str
    node: str
    updates_list: list
    total: float
    update: bool


@dataclasses.dataclass
class ProxmoxDiskData:
    """Data parsed from the Proxmox API for Disks."""

    type: str | None
    node: str | None
    size: float | None
    health: str | None
    serial: str | None
    model: str | None
    vendor: str | None
    path: str | None
    disk_rpm: float | None
    disk_type: str | None
    temperature: float | None
    power_cycles: int | None
