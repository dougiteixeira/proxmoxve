"""Models for Proxmox VE integration."""
from __future__ import annotations

from collections.abc import Callable
import dataclasses
from dataclasses import dataclass

from homeassistant.components.binary_sensor import BinarySensorEntityDescription
from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.components.switch import SwitchEntityDescription
from homeassistant.helpers.entity import EntityDescription


@dataclass
class ProxmoxEntityDescription(EntityDescription):
    """Describe a Proxmox entity."""


@dataclass
class ProxmoxBinarySensorDescription(BinarySensorEntityDescription):
    """Class describing Proxmox binarysensor entities."""

    unit_metric: str | None = None
    unit_imperial: str | None = None


@dataclass
class ProxmoxSensorDescription(SensorEntityDescription):
    """Class describing Proxmox sensor entities."""

    unit_metric: str | None = None
    unit_imperial: str | None = None
    conversion: Callable | None = None  # conversion factor to be applied to units
    calculation: Callable | None = None  # calculation


@dataclass
class ProxmoxSwitchDescription(SwitchEntityDescription):
    """Class describing Proxmox switch entities."""

    unit_metric: str | None = None
    unit_imperial: str | None = None
    start_command: str | None = None
    stop_command: str | None = None


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

    type: str
    node: str
    size: float
    health: str
    serial: str
    model: str
    vendor: str
    path: str
    disk_rpm: float
    disk_type: str
    temperature: float
    power_cycles: int