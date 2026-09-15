# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Constants for ProxmoxVE."""

import logging
from enum import StrEnum

DOMAIN = "proxmoxve"
PROXMOX_CLIENTS = "proxmox_clients"
CONF_TOKEN_NAME = "token_name"
CONF_REALM = "realm"
CONF_NODE = "node"
CONF_NODES = "nodes"
CONF_VMS = "vms"
CONF_CONTAINERS = "containers"
CONF_DISKS_ENABLE = "disks_enable"
CONF_TASKS_ENABLE = "tasks_enable"
CONF_GUEST_FILE_PATH = "guest_file_path"
CONF_HA_ADMIN_USERNAME = "ha_admin_username"
CONF_HA_ADMIN_TOKEN_NAME = "ha_admin_token_name"
CONF_HA_ADMIN_PASSWORD = "ha_admin_password"
CONF_HA_ADMIN_REALM = "ha_admin_realm"

GUEST_FILE_READ_MAX_BYTES = 4096

COORDINATORS = "coordinators"

DEFAULT_PORT = 8006
DEFAULT_REALM = "pam"
DEFAULT_VERIFY_SSL = True
UPDATE_INTERVAL = 60
# For everything that changes when a person changes it, rather than on its
# own: a certificate is replaced, a backup job is edited, a subscription is
# entered. Polling those at the usual interval would spend a request a minute
# to learn nothing, and this integration already makes plenty.
SLOW_UPDATE_INTERVAL = 3600

LOGGER = logging.getLogger(__package__)

CONF_CONTAINERS = "containers"
CONF_LXC = "lxc"
CONF_NODE = "node"
CONF_NODES = "nodes"
CONF_QEMU = "qemu"
CONF_REALM = "realm"
CONF_VMS = "vms"
CONF_STORAGE = "storage"

PROXMOX_CLIENT = "proxmox_client"
PROXMOX_HA_ADMIN_CLIENT = "proxmox_ha_admin_client"

INTEGRATION_TITLE = "Proxmox VE"
VERSION_REMOVE_YAML = "2025.1"


class ProxmoxType(StrEnum):
    """Proxmox type of information."""

    Proxmox = "proxmox"
    Node = "node"
    QEMU = "qemu"
    LXC = "lxc"
    Storage = "storage"
    Update = "update"
    Disk = "disk"
    Resources = "resources"
    ZFS = "zfs"
    Tasks = "tasks"
    Certificate = "certificate"
    BackupInfo = "backup_info"
    Subscription = "subscription"
    Replication = "replication"
    Ceph = "ceph"


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
    WAKEONLAN = "wakeonlan"
    UNLOCK = "unlock"
    ARM_HA = "arm-ha"
    DISARM_HA = "disarm-ha"


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
    LOCKED = "locked"
    GUEST_FILE_CONTENT = "guest_file_content"
    GUEST_FILE_PATH = "guest_file_path"
    NAME = "name"
    NETWORK_IN = "network_in"
    NETWORK_OUT = "network_out"
    UPDATE_TOTAL = "total"
    UPDATE_LIST = "updates_list"
    UPDATE_AVAIL = "update"
