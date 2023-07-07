"""Constants for ProxmoxVE."""

import logging

from homeassistant.backports.enum import StrEnum

DOMAIN = "proxmoxve"
PROXMOX_CLIENTS = "proxmox_clients"
CONF_REALM = "realm"
CONF_NODE = "node"
CONF_NODES = "nodes"
CONF_VMS = "vms"
CONF_CONTAINERS = "containers"

COORDINATORS = "coordinators"

DEFAULT_PORT = 8006
DEFAULT_REALM = "pam"
DEFAULT_VERIFY_SSL = True
UPDATE_INTERVAL = 60

LOGGER = logging.getLogger(__package__)

CONF_CONTAINERS = "containers"
CONF_LXC = "lxc"
CONF_NODE = "node"
CONF_NODES = "nodes"
CONF_QEMU = "qemu"
CONF_REALM = "realm"
CONF_VMS = "vms"

PROXMOX_CLIENT = "proxmox_client"

VERSION_REMOVE_YAML = "2023.8"


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
    HIBERNATE = "hibernate"


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
    SWAP_USED = "swap_used"
    DISK_TOTAL = "disk_total"
    DISK_USED = "disk_used"
    HEALTH = "health"
    NAME = "name"
    NETWORK_IN = "network_in"
    NETWORK_OUT = "network_out"
