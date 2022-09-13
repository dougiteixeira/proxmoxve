"""Constants for Proxmox integration."""
from __future__ import annotations

import logging

from homeassistant.backports.enum import StrEnum

DOMAIN = "proxmoxve"
INTEGRATION_NAME = "Proxmox VE"

LOGGER = logging.getLogger(__package__)

CONF_CONTAINERS = "containers"
CONF_LXC = "lxc"
CONF_NODE = "node"
CONF_NODES = "nodes"
CONF_QEMU = "qemu"
CONF_REALM = "realm"
CONF_VMS = "vms"

DEFAULT_PORT = 8006
DEFAULT_REALM = "pve"
DEFAULT_VERIFY_SSL = False

ID = "vmid"
COORDINATORS = "coordinators"
PROXMOX_CLIENT = "proxmox_client"


class ProxmoxType(StrEnum):
    """Proxmox type of information."""

    Proxmox = "proxmox"
    Node = "node"
    QEMU = "qemu"
    LXC = "lxc"


class ProxmoxCommand(StrEnum):
    """Proxmox commands Nodes/VM/CT."""

    REBOOT = "reboot"
    RESUME = "resume"
    SHUTDOWN = "shutdown"
    START = "start"
    STOP = "stop"
    SUSPEND = "suspend"
    RESET = "reset"
    START_ALL = "startall"
    STOP_ALL = "stopall"


class ProxmoxKeyAPIParse(StrEnum):
    """Proxmox key of data API parse."""

    VERSION = "version"
    STATUS = "status"
    UPTIME = "uptime"
    MODEL = "model"
    CPU = "cpu"
    MEMORY_USED = "memory_used"
    MEMORY_TOTAL = "memory_total"
    MEMORY_FREE = "memory_free"
    SWAP_TOTAL = "swap_total"
    SWAP_FREE = "swap_free"
    DISK_USED = "disk_used"
    DISK_TOTAL = "disk_total"
    HEALTH = "health"
    NAME = "name"
    NETWORK_IN = "network_in"
    NETWORK_OUT = "network_out"
