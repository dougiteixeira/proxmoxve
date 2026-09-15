# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Models for Proxmox VE integration."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

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
    sensors: dict[str, float] | None = None
    sensors_raw: str | None = None


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
    locked: bool | UndefinedType
    guest_file_content: str | UndefinedType
    guest_file_path: str | UndefinedType
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
    locked: bool | UndefinedType
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
class ProxmoxZFSData:
    """Data parsed from the Proxmox API for ZFS."""

    type: str
    node: str
    name: str
    health: str | UndefinedType
    size: float | UndefinedType
    alloc: float | UndefinedType
    free: float | UndefinedType


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
    disk_id: str | None
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
    wwn: str | None = None


@dataclasses.dataclass
class ProxmoxTaskData:
    """Data parsed from the Proxmox API for Tasks."""

    type: str
    node: str
    failed_count: int
    recent_failures: list[dict[str, str | int]] | UndefinedType
    last_failure_time: int | UndefinedType


@dataclasses.dataclass
class ProxmoxHAStatusData:
    """
    Data parsed from the Proxmox API for the cluster HA stack.

    Fields that the API may not report at all (an older pve-ha-manager
    without arm/disarm support, or a cluster whose CRM has never run) are
    UNDEFINED so the platforms can skip creating those entities, while
    fields that are only exposed as state attributes use plain values -
    the UNDEFINED sentinel is not JSON serializable.
    """

    type: str
    armed_state: str | UndefinedType
    resource_mode: str | None
    quorate: bool | UndefinedType
    crm_master: str | UndefinedType
    crm_master_last_seen: datetime | UndefinedType
    crm_master_stale: bool | UndefinedType
    ha_resources_total: int
    ha_resources_error: int
    ha_resources_error_list: list[dict[str, str]]


@dataclasses.dataclass
class ProxmoxCertificateData:
    """
    Data parsed from the Proxmox API for a node's TLS certificate.

    The API also returns the certificate itself in a `pem` field, a few
    kilobytes of it. That is deliberately not kept here: it would end up in
    a state attribute and in every diagnostics dump, and it says nothing a
    sensor can act on.
    """

    type: str
    node: str
    expires: datetime | UndefinedType
    # Exposed as state attributes, so plain values: the UNDEFINED sentinel is
    # not JSON serializable.
    filename: str | None
    subject: str | None
    issuer: str | None


@dataclasses.dataclass
class ProxmoxBackupInfoData:
    """
    Data parsed from the Proxmox API about backup coverage.

    `guests` is exposed as a state attribute, so it holds plain values: the
    UNDEFINED sentinel is not JSON serializable.
    """

    type: str
    guests_without_backup: int
    guests: list[dict[str, str | int]]


@dataclasses.dataclass
class ProxmoxSubscriptionData:
    """
    Data parsed from the Proxmox API for a node's subscription.

    The response also carries `key`, `serverid` and `signature`. None of them
    are kept: they identify the machine and the subscription itself, and would
    otherwise end up in a state attribute and in every diagnostics dump.

    The remaining fields are exposed as state attributes, so they hold plain
    values - the UNDEFINED sentinel is not JSON serializable.
    """

    type: str
    node: str
    status: str | UndefinedType
    level: str | None
    product: str | None
    next_due: str | None


@dataclasses.dataclass
class ProxmoxReplicationData:
    """
    Data parsed from the Proxmox API for a node's replication jobs.

    `failing_jobs` is exposed as a state attribute, so it holds plain values -
    the UNDEFINED sentinel is not JSON serializable.
    """

    type: str
    node: str
    jobs: int
    failing: bool
    oldest_sync: datetime | UndefinedType
    failing_jobs: list[dict[str, str | int]]


@dataclasses.dataclass
class ProxmoxCephData:
    """
    Data parsed from the Proxmox API for a Ceph cluster's health.

    `checks` is exposed as a state attribute, so it holds plain values - the
    UNDEFINED sentinel is not JSON serializable.
    """

    type: str
    health: str | UndefinedType
    checks: list[dict[str, str]]
