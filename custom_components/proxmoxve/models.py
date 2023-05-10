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

    model: str
    status: str
    version: str
    uptime: int
    cpu: float
    disk_total: float
    disk_used: float
    memory_total: float
    memory_used: float
    memory_free: float
    swap_total: float
    swap_free: float
    swap_used: float


@dataclasses.dataclass
class ProxmoxVMData:
    """Data parsed from the Proxmox API for QEMU."""

    name: str
    status: str
    node: str
    health: str
    uptime: int
    cpu: float
    memory_total: float
    memory_used: float
    memory_free: float
    network_in: float
    network_out: float
    disk_total: float
    disk_used: float


@dataclasses.dataclass
class ProxmoxLXCData:
    """Data parsed from the Proxmox API for LXC."""

    name: str
    status: str
    node: str
    uptime: int
    cpu: float
    memory_total: float
    memory_used: float
    memory_free: float
    network_in: float
    network_out: float
    disk_total: float
    disk_used: float
    swap_total: float
    swap_free: float
    swap_used: float
