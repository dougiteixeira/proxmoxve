# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""DataUpdateCoordinators for the Proxmox VE integration."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import quote
from zoneinfo import ZoneInfo

import homeassistant.util.dt as dt_util
from homeassistant.const import CONF_HOST, CONF_USERNAME
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.typing import UNDEFINED, UndefinedType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from proxmoxer import AuthenticationError, ProxmoxAPI
from proxmoxer.core import ResourceException
from requests.exceptions import (
    ConnectionError as connError,
)
from requests.exceptions import (
    ConnectTimeout,
    HTTPError,
    RetryError,
    SSLError,
)

from .api import get_api
from .const import (
    CONF_GUEST_FILE_PATH,
    CONF_HA_ADMIN_USERNAME,
    CONF_NODE,
    DOMAIN,
    GUEST_FILE_READ_MAX_BYTES,
    LOGGER,
    SLOW_UPDATE_INTERVAL,
    UPDATE_INTERVAL,
    ProxmoxType,
)
from .disk import disk_matches_id
from .models import (
    ProxmoxBackupInfoData,
    ProxmoxCephData,
    ProxmoxCertificateData,
    ProxmoxDiskData,
    ProxmoxHAStatusData,
    ProxmoxLXCData,
    ProxmoxNodeData,
    ProxmoxReplicationData,
    ProxmoxStorageData,
    ProxmoxSubscriptionData,
    ProxmoxTaskData,
    ProxmoxUpdateData,
    ProxmoxVMData,
    ProxmoxZFSData,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


def _try_parse_float(raw: object) -> float | None:
    """Try to parse a float from a value that may contain unit suffix."""
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        raw = raw.strip()
        for suffix in ("°C", "°F", "C", "F", "`C", " "):
            if raw.endswith(suffix):
                raw = raw[: -len(suffix)].strip()
                break
        try:
            return float(raw)
        except (ValueError, TypeError):
            return None
    return None


def _parse_sensors_dict(data: dict) -> dict[str, float]:
    """Parse raw sensors -j dict format: {chip: {sensor: {_input: value}}}."""
    result: dict[str, float] = {}
    for chip_name, chip_data in data.items():
        if not isinstance(chip_data, dict):
            continue
        for sensor_name, sensor_data in chip_data.items():
            if sensor_name == "adapter" or not isinstance(sensor_data, dict):
                continue
            for key, value in sensor_data.items():
                if key.endswith("_input"):
                    temp = _try_parse_float(value)
                    if temp is not None:
                        entry_name = f"{chip_name} {sensor_name}"
                        result[entry_name] = temp
    return result


# Values the Proxmox HA API documents for the "fencing" status entry
# (PVE::API2::HA::Status). Anything else is treated as unknown rather than
# passed on, so the enum sensor never reports a state outside its options.
HA_ARMED_STATES: Final[frozenset[str]] = frozenset(
    {"armed", "standby", "disarming", "disarmed"}
)
HA_RESOURCE_MODES: Final[frozenset[str]] = frozenset({"freeze", "ignore"})

# CRM service states that mean an incident is in progress: the guest is
# fenced, being recovered after a fence, or stuck in error. Read from
# `crm_state` (the raw CRM state) rather than `state`, which is a verbose
# display value the API rewrites to "ignore" while HA is disarmed.
HA_SERVICE_ERROR_STATES: Final[frozenset[str]] = frozenset(
    {"error", "fence", "recovery"}
)

# How old the CRM master timestamp may get before the master counts as dead.
# PVE::API2::HA::Status uses the same 30 s (`$tdiff > 30` -> "old timestamp -
# dead?"), but only inside its localized display string, so the check is
# repeated here on the structured timestamp. Proxmox compares against its own
# clock; here it is the Home Assistant clock, so a host whose time is out of
# sync with the cluster can report a false positive.
HA_CRM_MASTER_DEAD_AFTER: Final[timedelta] = timedelta(seconds=30)

# How long a node's last hardware readings stay usable when a poll comes
# back without any. PVE-mods collects on demand: a worker writes the
# `sensors` output to a file under /run and removes it again after ten
# seconds of inactivity, so a poll that arrives cold gets an empty field
# and the data only lands a second later. A reading a few minutes old is
# far more useful than a hole in the graph, but past this the data really
# is gone rather than late.
SENSORS_HOLD_FOR: Final[timedelta] = timedelta(minutes=10)


def _parse_ha_enum(
    entry: dict[str, Any],
    key: str,
    allowed: frozenset[str],
) -> str | UndefinedType:
    """Return an enum field of an HA status entry, or UNDEFINED if unusable."""
    value = entry.get(key)
    if value in allowed:
        return value
    if value is not None:
        LOGGER.warning(
            "Unknown value '%s' for Proxmox HA status field '%s', ignoring it",
            value,
            key,
        )
    return UNDEFINED


def _positive_or_undefined(value: Any) -> Any:
    """Return a number only when it is above zero, else UNDEFINED."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return value
    return UNDEFINED


def qemu_memory_used(api_status: dict[str, Any]) -> int | UndefinedType:
    """
    Return what a QEMU guest uses, preferring the guest's own figure.

    `mem` only holds the guest's usage while its balloon driver reports
    statistics. Without them Proxmox falls back to the host-side resident size
    of the QEMU process, which carries emulator overhead and can exceed the
    configured memory - that is how a "memory used percentage" above 100%
    happens. Two responses from the same cluster show both shapes: a Linux
    guest reports `ballooninfo.total_mem` and `free_mem` whose difference is
    exactly `mem`, while a guest without a balloon driver reports neither and
    gets `mem` equal to `memhost`.

    So read the guest's own numbers when they are there, and fall back to
    `mem` - which is then the only figure Proxmox itself has - when they are
    not.
    """
    balloon = api_status.get("ballooninfo")
    if isinstance(balloon, dict):
        total = balloon.get("total_mem")
        free = balloon.get("free_mem")
        if (
            isinstance(total, int)
            and isinstance(free, int)
            and not isinstance(total, bool)
            and not isinstance(free, bool)
            and total >= free >= 0
        ):
            return total - free
    return api_status.get("mem", UNDEFINED)


# The certificate serving the API and web interface. `pveproxy-ssl.pem` is
# the one an administrator replaces - with an ACME certificate, or their own
# - and it only exists once that has happened; otherwise the node falls back
# to `pve-ssl.pem`, issued by the cluster's own CA. `pve-root-ca.pem` is that
# CA and is deliberately ignored: it is valid for ten years and its expiry is
# not something anyone acts on.
CERTIFICATE_PREFERENCE: Final[tuple[str, ...]] = ("pveproxy-ssl.pem", "pve-ssl.pem")


def _certificate_timestamp(value: Any) -> datetime | UndefinedType:
    """Turn a certificate's unix timestamp into an aware datetime."""
    if value is None:
        return UNDEFINED
    try:
        return dt_util.utc_from_timestamp(float(value))
    except (TypeError, ValueError, OverflowError, OSError):
        LOGGER.warning("Unusable timestamp '%s' in Proxmox certificate info", value)
        return UNDEFINED


def parse_certificates(
    entries: list[dict[str, Any]],
    node_name: str,
) -> ProxmoxCertificateData:
    """
    Pick the certificate that serves the API out of `certificates/info`.

    The endpoint returns one entry per certificate file that exists, so a node
    without a replaced certificate reports two and one with a custom or ACME
    certificate reports three.
    """
    by_filename = {
        entry["filename"]: entry
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("filename"), str)
    }

    chosen: dict[str, Any] = {}
    for filename in CERTIFICATE_PREFERENCE:
        if filename in by_filename:
            chosen = by_filename[filename]
            break

    return ProxmoxCertificateData(
        type=ProxmoxType.Certificate,
        node=node_name,
        expires=_certificate_timestamp(chosen.get("notafter")),
        filename=chosen.get("filename"),
        subject=chosen.get("subject"),
        issuer=chosen.get("issuer"),
    )


def parse_backup_info(entries: list[dict[str, Any]]) -> ProxmoxBackupInfoData:
    """
    Build backup coverage from `cluster/backup-info/not-backed-up` entries.

    The endpoint lists every guest that no backup job covers, so an empty
    response is the good case. Proxmox already filters it to guests the
    credentials may see, which means the count is "not backed up, as far as
    this user can tell" rather than a cluster-wide truth.
    """
    guests: list[dict[str, str | int]] = []

    for entry in entries:
        if not isinstance(entry, dict) or "vmid" not in entry:
            continue
        guest: dict[str, str | int] = {"vmid": entry["vmid"]}
        if isinstance(entry.get("type"), str):
            guest["type"] = entry["type"]
        if isinstance(entry.get("name"), str):
            guest["name"] = entry["name"]
        guests.append(guest)

    return ProxmoxBackupInfoData(
        type=ProxmoxType.BackupInfo,
        guests_without_backup=len(guests),
        guests=guests,
    )


# The states Proxmox documents for a node's subscription
# (PVE::API2::Subscription). Anything else is treated as unknown rather than
# passed on, so the enum sensor never reports a state outside its options.
SUBSCRIPTION_STATES: Final[frozenset[str]] = frozenset(
    {"new", "notfound", "active", "invalid", "expired", "suspended"}
)


# Ceph's own health states, mapped to the values the enum sensor offers.
# `cluster/ceph/status` hands through what `ceph -s` reports rather than a
# schema Proxmox defines, so anything outside this set is treated as unknown.
CEPH_HEALTH_STATES: Final[dict[str, str]] = {
    "HEALTH_OK": "ok",
    "HEALTH_WARN": "warning",
    "HEALTH_ERR": "error",
}


def parse_ceph(api_status: dict[str, Any]) -> ProxmoxCephData:
    """
    Build Ceph health from `cluster/ceph/status`.

    Only the health block is read. The response also carries the OSD, monitor
    and placement group maps, which are a different question and a great deal
    of data to put behind a sensor.
    """
    health_block = api_status.get("health")
    health_block = health_block if isinstance(health_block, dict) else {}

    raw = health_block.get("status")
    health: str | UndefinedType = CEPH_HEALTH_STATES.get(raw, UNDEFINED)
    if health is UNDEFINED and raw is not None:
        LOGGER.warning("Unknown Ceph health status '%s', ignoring it", raw)

    checks: list[dict[str, str]] = []
    raw_checks = health_block.get("checks")
    if isinstance(raw_checks, dict):
        for name, check in raw_checks.items():
            if not isinstance(check, dict):
                continue
            entry = {"check": str(name)}
            if isinstance(severity := check.get("severity"), str):
                entry["severity"] = severity
            summary = check.get("summary")
            if isinstance(summary, dict) and isinstance(
                message := summary.get("message"), str
            ):
                entry["message"] = message
            checks.append(entry)

    return ProxmoxCephData(
        type=ProxmoxType.Ceph,
        health=health,
        checks=checks,
    )


def parse_replication(
    entries: list[dict[str, Any]],
    node_name: str,
) -> ProxmoxReplicationData:
    """
    Build replication health from `nodes/{node}/replication` entries.

    Disabled jobs are counted but never raise the alarm or hold back the
    oldest sync: somebody turned them off on purpose.

    The oldest successful sync across the active jobs is the useful one - it
    says how far behind the furthest-behind target is, where the newest would
    hide a job that stopped replicating days ago.
    """
    jobs = 0
    failing_jobs: list[dict[str, str | int]] = []
    sync_times: list[datetime] = []

    for entry in entries:
        if not isinstance(entry, dict) or "id" not in entry:
            continue
        jobs += 1
        if entry.get("disable"):
            continue

        if (fail_count := entry.get("fail_count")) and isinstance(fail_count, int):
            job: dict[str, str | int] = {"id": str(entry["id"]), "failures": fail_count}
            for key, field in (
                ("guest", "guest"),
                ("guest_type", "vmtype"),
                ("target", "target"),
            ):
                if (value := entry.get(field)) is not None:
                    job[key] = value if isinstance(value, int) else str(value)
            if isinstance(error := entry.get("error"), str):
                job["error"] = error
            failing_jobs.append(job)

        if (last_sync := entry.get("last_sync")) and isinstance(
            last_sync, (int, float)
        ):
            try:
                sync_times.append(dt_util.utc_from_timestamp(float(last_sync)))
            except (TypeError, ValueError, OverflowError, OSError):
                LOGGER.warning(
                    "Unusable last_sync '%s' in Proxmox replication status", last_sync
                )

    return ProxmoxReplicationData(
        type=ProxmoxType.Replication,
        node=node_name,
        jobs=jobs,
        failing=bool(failing_jobs),
        oldest_sync=min(sync_times) if sync_times else UNDEFINED,
        failing_jobs=failing_jobs,
    )


def parse_subscription(
    api_status: dict[str, Any],
    node_name: str,
) -> ProxmoxSubscriptionData:
    """
    Build a node's subscription state from `nodes/{node}/subscription`.

    `key`, `serverid` and `signature` are read past deliberately: they
    identify the machine and the subscription, and nothing here needs them.
    """
    status = api_status.get("status")
    if status not in SUBSCRIPTION_STATES:
        if status is not None:
            LOGGER.warning(
                "Unknown Proxmox subscription status '%s', ignoring it", status
            )
        status = UNDEFINED

    return ProxmoxSubscriptionData(
        type=ProxmoxType.Subscription,
        node=node_name,
        status=status,
        level=api_status.get("level"),
        product=api_status.get("productname"),
        next_due=api_status.get("nextduedate"),
    )


def parse_ha_status(entries: list[dict[str, Any]]) -> ProxmoxHAStatusData:
    """
    Build the cluster HA status from `cluster/ha/status/current` entries.

    Only the structured fields of each entry are read; the `status` field is
    a localized display string ("node1 (active, watchdog active, <time>)")
    and must not be parsed.
    """
    armed_state: str | UndefinedType = UNDEFINED
    resource_mode: str | None = None
    quorate: bool | UndefinedType = UNDEFINED
    crm_master: str | UndefinedType = UNDEFINED
    crm_master_last_seen: datetime | UndefinedType = UNDEFINED
    crm_master_stale: bool | UndefinedType = UNDEFINED
    resources_total = 0
    resources_error: list[dict[str, str]] = []

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        match entry.get("type"):
            case "quorum":
                # PVE serializes the boolean as 1/0 depending on version.
                if (value := entry.get("quorate")) is not None:
                    quorate = value in (True, 1, "1")
            case "master":
                if (node := entry.get("node")) is not None:
                    crm_master = str(node)
                if (timestamp := entry.get("timestamp")) is not None:
                    try:
                        crm_master_last_seen = dt_util.utc_from_timestamp(
                            float(timestamp)
                        )
                    except (TypeError, ValueError, OverflowError, OSError):
                        LOGGER.warning(
                            "Unusable timestamp '%s' in Proxmox HA master status",
                            timestamp,
                        )
                    else:
                        crm_master_stale = (
                            dt_util.utcnow() - crm_master_last_seen
                            > HA_CRM_MASTER_DEAD_AFTER
                        )
            case "fencing":
                armed_state = _parse_ha_enum(entry, "armed-state", HA_ARMED_STATES)
                mode = _parse_ha_enum(entry, "resource_mode", HA_RESOURCE_MODES)
                resource_mode = None if mode is UNDEFINED else str(mode)
            case "service":
                resources_total += 1
                if (crm_state := entry.get("crm_state")) in HA_SERVICE_ERROR_STATES:
                    resources_error.append(
                        {
                            "sid": str(entry.get("sid", "")),
                            "node": str(entry.get("node", "")),
                            "crm_state": str(crm_state),
                        }
                    )

    return ProxmoxHAStatusData(
        type=ProxmoxType.Proxmox,
        armed_state=armed_state,
        resource_mode=resource_mode,
        quorate=quorate,
        crm_master=crm_master,
        crm_master_last_seen=crm_master_last_seen,
        crm_master_stale=crm_master_stale,
        ha_resources_total=resources_total,
        ha_resources_error=len(resources_error),
        ha_resources_error_list=resources_error,
    )


class ProxmoxCoordinator(
    DataUpdateCoordinator[
        ProxmoxBackupInfoData
        | ProxmoxCephData
        | ProxmoxCertificateData
        | ProxmoxDiskData
        | ProxmoxHAStatusData
        | ProxmoxLXCData
        | ProxmoxNodeData
        | ProxmoxReplicationData
        | ProxmoxStorageData
        | ProxmoxSubscriptionData
        | ProxmoxTaskData
        | ProxmoxUpdateData
        | ProxmoxVMData
        | ProxmoxZFSData
    ]
):
    """Proxmox VE data update coordinator."""


class ProxmoxHAResourcesCoordinator(DataUpdateCoordinator[set[str]]):
    """
    Track which guests are managed by the Proxmox HA stack.

    Cluster-wide (`Sys.Audit` on `/`), so it uses the optional HA-admin
    client rather than the primary least-privilege one, and is shared by
    every guest's "HA managed" binary sensor instead of being polled once
    per guest.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        proxmox: ProxmoxAPI,
    ) -> None:
        """Initialize the Proxmox HA resources coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name="proxmox_coordinator_ha_resources",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

        self.hass = hass
        self.config_entry: ConfigEntry = self.config_entry
        self.proxmox = proxmox
        self.resource_id = "ha_resources"
        self.api_category = ProxmoxType.Proxmox

    async def _async_update_data(self) -> set[str]:
        """Return the set of HA-managed resource sids (e.g. 'vm:100', 'ct:105')."""
        resources = await self.hass.async_add_executor_job(
            poll_api,
            self.hass,
            self.config_entry,
            self.proxmox,
            "cluster/ha/resources",
            ProxmoxType.Proxmox,
            self.resource_id,
        )
        return {
            resource["sid"]
            for resource in (resources or [])
            if isinstance(resource, dict) and "sid" in resource
        }


class ProxmoxHAStatusCoordinator(ProxmoxCoordinator):
    """
    Proxmox VE cluster HA status coordinator.

    Cluster-wide (`Sys.Audit` on `/`), so it uses the optional HA-admin
    client like ProxmoxHAResourcesCoordinator. It is kept separate from
    that coordinator on purpose: `cluster/ha/status/current` also reports
    services the CRM still tracks but that are no longer configured HA
    resources, so deriving the "HA managed" set from it would keep those
    sensors on after a resource is removed.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        proxmox: ProxmoxAPI,
    ) -> None:
        """Initialize the Proxmox cluster HA status coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name="proxmox_coordinator_ha_status",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

        self.hass = hass
        self.config_entry: ConfigEntry = self.config_entry
        self.proxmox = proxmox
        self.resource_id = "ha_status"
        self.api_category = ProxmoxType.Proxmox

    async def _async_update_data(self) -> ProxmoxHAStatusData:
        """Update the cluster HA status."""
        api_status = await self.hass.async_add_executor_job(
            poll_api,
            self.hass,
            self.config_entry,
            self.proxmox,
            "cluster/ha/status/current",
            ProxmoxType.Proxmox,
            self.resource_id,
        )

        # poll_api returns None when the HA-admin credentials lack Sys.Audit
        # on `/` (a repair issue is raised there). Failing the update marks
        # the entities unavailable instead of reporting a made-up status.
        if api_status is None:
            msg = "Cluster HA status is not available"
            raise UpdateFailed(msg)

        return parse_ha_status(api_status)


class ProxmoxBackupInfoCoordinator(ProxmoxCoordinator):
    """
    Proxmox VE backup coverage coordinator.

    Cluster-wide (`Sys.Audit` on `/`), so it uses the optional cluster
    credentials like the HA coordinators rather than the primary
    least-privilege ones.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        proxmox: ProxmoxAPI,
    ) -> None:
        """Initialize the Proxmox backup info coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name="proxmox_coordinator_backup_info",
            update_interval=timedelta(seconds=SLOW_UPDATE_INTERVAL),
        )

        self.hass = hass
        self.config_entry: ConfigEntry = self.config_entry
        self.proxmox = proxmox
        self.resource_id = "backup_info"
        self.api_category = ProxmoxType.Proxmox

    async def _async_update_data(self) -> ProxmoxBackupInfoData:
        """Update which guests no backup job covers."""
        api_status = await self.hass.async_add_executor_job(
            poll_api,
            self.hass,
            self.config_entry,
            self.proxmox,
            "cluster/backup-info/not-backed-up",
            ProxmoxType.Proxmox,
            self.resource_id,
        )

        if api_status is None:
            msg = "Backup coverage is not available"
            raise UpdateFailed(msg)

        return parse_backup_info(api_status)


class ProxmoxReplicationCoordinator(ProxmoxCoordinator):
    """Proxmox VE node replication data update coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        proxmox: ProxmoxAPI,
        node_name: str,
    ) -> None:
        """Initialize the Proxmox replication coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name=f"proxmox_coordinator_replication_{node_name}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

        self.hass = hass
        self.config_entry: ConfigEntry = self.config_entry
        self.proxmox = proxmox
        self.node_name = node_name
        self.resource_id = f"{ProxmoxType.Replication.capitalize()} {node_name}"

    async def _async_update_data(self) -> ProxmoxReplicationData:
        """Update the node's replication jobs."""
        # Proxmox filters this to guests the credentials may audit, so the
        # least-privilege client sees exactly the jobs it is entitled to.
        api_status = await self.hass.async_add_executor_job(
            poll_api,
            self.hass,
            self.config_entry,
            self.proxmox,
            f"nodes/{self.node_name}/replication",
            ProxmoxType.Node,
            self.node_name,
        )

        if api_status is None:
            msg = f"Replication status for {self.node_name} is not available"
            raise UpdateFailed(msg)

        return parse_replication(api_status, self.node_name)


class ProxmoxSubscriptionCoordinator(ProxmoxCoordinator):
    """Proxmox VE node subscription data update coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        proxmox: ProxmoxAPI,
        node_name: str,
    ) -> None:
        """Initialize the Proxmox subscription coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name=f"proxmox_coordinator_subscription_{node_name}",
            update_interval=timedelta(seconds=SLOW_UPDATE_INTERVAL),
        )

        self.hass = hass
        self.config_entry: ConfigEntry = self.config_entry
        self.proxmox = proxmox
        self.node_name = node_name
        self.resource_id = f"{ProxmoxType.Subscription.capitalize()} {node_name}"

    async def _async_update_data(self) -> ProxmoxSubscriptionData:
        """Update the node's subscription state."""
        # Needs no permission beyond being logged in, so it uses the same
        # least-privilege credentials as everything else.
        api_status = await self.hass.async_add_executor_job(
            poll_api,
            self.hass,
            self.config_entry,
            self.proxmox,
            f"nodes/{self.node_name}/subscription",
            ProxmoxType.Node,
            self.node_name,
        )

        if not isinstance(api_status, dict):
            msg = f"Subscription information for {self.node_name} is not available"
            raise UpdateFailed(msg)

        return parse_subscription(api_status, self.node_name)


class ProxmoxCephCoordinator(ProxmoxCoordinator):
    """
    Proxmox VE Ceph health coordinator.

    Cluster-wide (`Sys.Audit` or `Datastore.Audit` on `/`), so it uses the
    optional cluster credentials like the HA and backup coordinators.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        proxmox: ProxmoxAPI,
    ) -> None:
        """Initialize the Proxmox Ceph coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name="proxmox_coordinator_ceph",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

        self.hass = hass
        self.config_entry: ConfigEntry = self.config_entry
        self.proxmox = proxmox
        self.resource_id = "ceph"
        self.api_category = ProxmoxType.Proxmox

    async def _async_update_data(self) -> ProxmoxCephData:
        """Update the Ceph cluster health."""
        api_status = await self.hass.async_add_executor_job(
            poll_api,
            self.hass,
            self.config_entry,
            self.proxmox,
            "cluster/ceph/status",
            ProxmoxType.Proxmox,
            self.resource_id,
        )

        if not isinstance(api_status, dict):
            msg = "Ceph status is not available"
            raise UpdateFailed(msg)

        return parse_ceph(api_status)


class ProxmoxCertificateCoordinator(ProxmoxCoordinator):
    """Proxmox VE node certificate data update coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        proxmox: ProxmoxAPI,
        node_name: str,
    ) -> None:
        """Initialize the Proxmox certificate coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name=f"proxmox_coordinator_certificate_{node_name}",
            update_interval=timedelta(seconds=SLOW_UPDATE_INTERVAL),
        )

        self.hass = hass
        self.config_entry: ConfigEntry = self.config_entry
        self.proxmox = proxmox
        self.node_name = node_name
        self.resource_id = f"{ProxmoxType.Certificate.capitalize()} {node_name}"

    async def _async_update_data(self) -> ProxmoxCertificateData:
        """Update the node's certificate information."""
        # This endpoint needs no permission beyond being logged in, so it is
        # read with the same least-privilege credentials as everything else.
        api_status = await self.hass.async_add_executor_job(
            poll_api,
            self.hass,
            self.config_entry,
            self.proxmox,
            f"nodes/{self.node_name}/certificates/info",
            ProxmoxType.Node,
            self.node_name,
        )

        if api_status is None:
            msg = f"Certificate information for {self.node_name} is not available"
            raise UpdateFailed(msg)

        return parse_certificates(api_status, self.node_name)


class ProxmoxNodeCoordinator(ProxmoxCoordinator):
    """Proxmox VE Node data update coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        proxmox: ProxmoxAPI,
        api_category: str,
        node_name: str,
    ) -> None:
        """Initialize the Proxmox Node coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name=f"proxmox_coordinator_{api_category}_{node_name}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

        self.hass = hass
        self.config_entry: ConfigEntry = self.config_entry
        self.proxmox = proxmox
        self.resource_id = node_name
        self.api_category = api_category
        self._last_sensors: dict[str, float] = {}
        self._last_sensors_raw: str | None = None
        self._last_sensors_at: datetime | None = None

    def _hold_last_sensors(
        self,
        sensors: dict[str, float],
        sensors_raw: str | None,
    ) -> tuple[dict[str, float], str | None]:
        """
        Keep the previous hardware readings when a poll brings none.

        PVE-mods collects on demand and tears the collection down again
        after a few seconds idle, so a poll can easily arrive before there
        is anything to read. Blanking every temperature because one response
        came back empty produces a gap in the history that says "no reading"
        where the truth is "not this time".

        The readings are only held for SENSORS_HOLD_FOR. Past that, whatever
        provides them is gone rather than late - PVE-mods removed, the module
        unloaded - and reporting nothing is then the honest answer.
        """
        now = dt_util.utcnow()

        if sensors:
            self._last_sensors = sensors
            self._last_sensors_raw = sensors_raw
            self._last_sensors_at = now
            return sensors, sensors_raw

        if self._last_sensors_at is None:
            return sensors, sensors_raw

        age = now - self._last_sensors_at
        if age > SENSORS_HOLD_FOR:
            LOGGER.debug(
                "No hardware sensor data for node %s in %s, dropping the last readings",
                self.resource_id,
                age,
            )
            self._last_sensors = {}
            self._last_sensors_raw = None
            self._last_sensors_at = None
            return sensors, sensors_raw

        LOGGER.debug(
            "Node %s reported no hardware sensor data, keeping readings from %s ago",
            self.resource_id,
            age,
        )
        return self._last_sensors, self._last_sensors_raw

    async def _async_update_data(self) -> ProxmoxNodeData:
        """Update data  for Proxmox Node."""
        api_path = "nodes"
        node_status = ""
        node_api = {}
        api_status = {}
        if nodes_api := await self.hass.async_add_executor_job(
            poll_api,
            self.hass,
            self.config_entry,
            self.proxmox,
            api_path,
            ProxmoxType.Node,
            self.resource_id,
        ):
            for node_api in nodes_api:
                if node_api[CONF_NODE] == self.resource_id:
                    node_status = node_api["status"]
                    break
            if node_status == "":
                LOGGER.debug("Node %s status is %s", self.resource_id, node_status)
                node_status = "offline"

        if node_status == "online":
            api_path = f"nodes/{self.resource_id}/status"
            api_status = await self.hass.async_add_executor_job(
                poll_api,
                self.hass,
                self.config_entry,
                self.proxmox,
                api_path,
                ProxmoxType.Node,
                self.resource_id,
            )
            if api_status is None:
                msg = f"Node {self.resource_id} unable to be found in host {self.config_entry.data[CONF_HOST]}"
                raise UpdateFailed(msg)

            api_status["status"] = node_api["status"]
            api_status["cpu"] = node_api["cpu"]
            api_status["disk_max"] = node_api["maxdisk"]
            api_status["disk_used"] = node_api["disk"]

            api_path = f"nodes/{self.resource_id}/version"
            api_status["version"] = await self.hass.async_add_executor_job(
                poll_api,
                self.hass,
                self.config_entry,
                self.proxmox,
                api_path,
                ProxmoxType.Node,
                self.resource_id,
            )

            api_path = f"nodes/{self.resource_id}/qemu"
            qemu_status = await self.hass.async_add_executor_job(
                poll_api,
                self.hass,
                self.config_entry,
                self.proxmox,
                api_path,
                ProxmoxType.QEMU,
                self.resource_id,
            )
            node_qemu: dict[str, Any] = {}
            node_qemu_on: int = 0
            node_qemu_on_list: list[str] = []
            for qemu in qemu_status if qemu_status is not None else []:
                if "status" in qemu and qemu["status"] == "running":
                    node_qemu_on += 1
                    node_qemu_on_list.append(f"{qemu['name']} ({qemu['vmid']})")
            node_qemu["total"] = node_qemu_on
            node_qemu["list"] = node_qemu_on_list
            api_status["qemu"] = node_qemu

            api_path = f"nodes/{self.resource_id}/lxc"
            lxc_status = await self.hass.async_add_executor_job(
                poll_api,
                self.hass,
                self.config_entry,
                self.proxmox,
                api_path,
                ProxmoxType.LXC,
                self.resource_id,
            )
            node_lxc: dict[str, Any] = {}
            node_lxc_on: int = 0
            node_lxc_on_list: list[str] = []
            for lxc in lxc_status if lxc_status is not None else []:
                if lxc["status"] == "running":
                    node_lxc_on += 1
                    node_lxc_on_list.append(f"{lxc['name']} ({lxc['vmid']})")
            node_lxc["total"] = node_lxc_on
            node_lxc["list"] = node_lxc_on_list
            api_status["lxc"] = node_lxc

        sensors: dict[str, float] = {}
        sensors_raw: str | None = None
        if sensors_output := api_status.get("sensorsOutput"):
            # Legacy PVE-mods script (pve-mod-gui-sensors.sh): raw `sensors -j`
            # JSON as a string.
            sensors_raw = sensors_output
            try:
                parsed = json.loads(sensors_output)
                if isinstance(parsed, dict):
                    sensors = _parse_sensors_dict(parsed)
            except (json.JSONDecodeError, TypeError):
                LOGGER.debug(
                    "Failed to parse sensorsOutput for node %s", self.resource_id
                )
        elif isinstance(
            v2_sensor_info := api_status.get("PveMod_JsonSensorInfo"), dict
        ):
            # PVE-mods v2 (node_info package): already-decoded object, with
            # the `sensors -j`-shaped data nested under
            # data["PVE MOD lm-sensors Enhanced"] and extra per-chip
            # metadata (Adapter/model/serial/cpu_model/...) mixed in
            # alongside the sensor readings; _parse_sensors_dict already
            # ignores anything whose keys don't end in "_input".
            lm_sensors_data = v2_sensor_info.get("data", {}).get(
                "PVE MOD lm-sensors Enhanced"
            )
            if isinstance(lm_sensors_data, dict):
                sensors = _parse_sensors_dict(lm_sensors_data)
                sensors_raw = json.dumps(lm_sensors_data)
            else:
                LOGGER.debug(
                    "Node %s returned PveMod_JsonSensorInfo without the expected "
                    "lm-sensors block",
                    self.resource_id,
                )
        else:
            LOGGER.debug(
                "Node %s status carried no hardware sensor data at all",
                self.resource_id,
            )

        sensors, sensors_raw = self._hold_last_sensors(sensors, sensors_raw)

        if node_status != "":
            return ProxmoxNodeData(
                type=ProxmoxType.Node,
                model=(
                    api_status["cpuinfo"]["model"]
                    if (("cpuinfo" in api_status) and "model" in api_status["cpuinfo"])
                    else UNDEFINED
                ),
                status=api_status.get("status", "Offline"),
                version=(
                    api_status["version"].get("version", UNDEFINED)
                    if ("version" in api_status)
                    else UNDEFINED
                ),
                uptime=api_status.get("uptime", UNDEFINED),
                cpu=api_status.get("cpu", UNDEFINED),
                disk_total=api_status.get("disk_max", UNDEFINED),
                disk_used=api_status.get("disk_used", UNDEFINED),
                memory_total=(
                    api_status["memory"]["total"]
                    if (("memory" in api_status) and "total" in api_status["memory"])
                    else UNDEFINED
                ),
                memory_used=(
                    api_status["memory"]["used"]
                    if (("memory" in api_status) and "used" in api_status["memory"])
                    else UNDEFINED
                ),
                memory_free=(
                    api_status["memory"]["free"]
                    if (("memory" in api_status) and "free" in api_status["memory"])
                    else UNDEFINED
                ),
                swap_total=(
                    api_status["swap"]["total"]
                    if (("swap" in api_status) and "total" in api_status["swap"])
                    else UNDEFINED
                ),
                swap_free=(
                    api_status["swap"]["free"]
                    if (("swap" in api_status) and "free" in api_status["swap"])
                    else UNDEFINED
                ),
                swap_used=(
                    api_status["swap"]["used"]
                    if (("swap" in api_status) and "used" in api_status["swap"])
                    else UNDEFINED
                ),
                qemu_on=(
                    api_status["qemu"]["total"]
                    if (("qemu" in api_status) and "total" in api_status["qemu"])
                    else 0
                ),
                qemu_on_list=(
                    api_status["qemu"]["list"]
                    if (("qemu" in api_status) and "list" in api_status["qemu"])
                    else UNDEFINED
                ),
                lxc_on=(
                    api_status["lxc"]["total"]
                    if (("lxc" in api_status) and "total" in api_status["lxc"])
                    else 0
                ),
                lxc_on_list=(
                    api_status["lxc"]["list"]
                    if (("lxc" in api_status) and "list" in api_status["lxc"])
                    else UNDEFINED
                ),
                sensors=sensors,
                sensors_raw=sensors_raw,
            )
        msg = f"Node {self.resource_id} unable to be found in host {self.config_entry.data[CONF_HOST]}"
        raise UpdateFailed(msg)


class ProxmoxQEMUCoordinator(ProxmoxCoordinator):
    """Proxmox VE QEMU data update coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        proxmox: ProxmoxAPI,
        api_category: str,
        qemu_id: int,
    ) -> None:
        """Initialize the Proxmox QEMU coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name=f"proxmox_coordinator_{api_category}_{qemu_id}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

        self.hass = hass
        self.config_entry: ConfigEntry = self.config_entry
        self.proxmox = proxmox
        self.node_name: str
        self.resource_id = qemu_id

    async def _async_update_data(self) -> ProxmoxVMData:
        """Update data  for Proxmox QEMU."""
        node_name = None
        api_status = None

        api_path = "cluster/resources"
        resources = await self.hass.async_add_executor_job(
            poll_api,
            self.hass,
            self.config_entry,
            self.proxmox,
            api_path,
            ProxmoxType.Resources,
            None,
        )

        for resource in resources if resources is not None else []:
            if "vmid" in resource:
                if int(resource["vmid"]) == int(self.resource_id):
                    node_name = resource["node"]

        if node_name is not None:
            api_path = f"nodes/{node_name!s}/qemu/{self.resource_id}/status/current"
            api_status = await self.hass.async_add_executor_job(
                poll_api,
                self.hass,
                self.config_entry,
                self.proxmox,
                api_path,
                ProxmoxType.QEMU,
                self.resource_id,
            )

        if api_status is None or "status" not in api_status:
            msg = f"QEMU {self.resource_id} unable to be found"
            raise UpdateFailed(msg)

        guest_disk_used: int | UndefinedType = UNDEFINED
        guest_disk_total: int | UndefinedType = UNDEFINED

        try:
            fsinfo_path = (
                f"nodes/{node_name!s}/qemu/{self.resource_id}/agent/get-fsinfo"
            )
            fsinfo = await self.hass.async_add_executor_job(
                poll_api,
                self.hass,
                self.config_entry,
                self.proxmox,
                fsinfo_path,
                ProxmoxType.QEMU,
                self.resource_id,
            )

            entries = fsinfo.get("result", []) if isinstance(fsinfo, dict) else fsinfo

            if isinstance(entries, list):
                filesystems_used_by_device: dict[str, int] = {}
                filesystems_total_by_device: dict[str, int] = {}

                for fs in entries:
                    if not isinstance(fs, dict):
                        continue

                    disks = fs.get("disk") or []
                    if not disks:
                        continue

                    disk0 = disks[0]
                    device_key = disk0.get("dev") or fs.get("name")

                    used = fs.get("used-bytes")
                    total = fs.get("total-bytes")
                    if not device_key or not isinstance(used, (int, float)):
                        continue

                    filesystems_used_by_device[device_key] = max(
                        filesystems_used_by_device.get(device_key, 0),
                        int(used),
                    )
                    if isinstance(total, (int, float)):
                        filesystems_total_by_device[device_key] = max(
                            filesystems_total_by_device.get(device_key, 0),
                            int(total),
                        )

                if filesystems_used_by_device:
                    guest_disk_used = sum(filesystems_used_by_device.values())
                    # Only trust the guest-reported total if every filesystem
                    # that contributed to guest_disk_used also reported one,
                    # otherwise the two numbers count a different set of
                    # filesystems.
                    if (
                        filesystems_total_by_device.keys()
                        == filesystems_used_by_device.keys()
                    ):
                        guest_disk_total = sum(filesystems_total_by_device.values())

        except UpdateFailed:
            pass

        guest_file_path = self.config_entry.options.get(CONF_GUEST_FILE_PATH)
        guest_file_content: str | UndefinedType = UNDEFINED

        if guest_file_path:
            try:
                file_read_path = (
                    f"nodes/{node_name!s}/qemu/{self.resource_id}/agent/file-read"
                    f"?file={quote(guest_file_path, safe='')}"
                    f"&count={GUEST_FILE_READ_MAX_BYTES}&decode=1"
                )
                file_result = await self.hass.async_add_executor_job(
                    poll_api,
                    self.hass,
                    self.config_entry,
                    self.proxmox,
                    file_read_path,
                    ProxmoxType.QEMU,
                    self.resource_id,
                )
                if isinstance(file_result, dict) and isinstance(
                    file_result.get("content"), str
                ):
                    guest_file_content = file_result["content"]
            except UpdateFailed:
                pass

        update_device_via(self, ProxmoxType.QEMU, node_name)

        memory_total = api_status.get("maxmem", UNDEFINED)
        memory_used = qemu_memory_used(api_status)
        memory_free = (
            # The host-side fallback can exceed the configured memory, and a
            # negative number of free bytes would be nonsense.
            max(memory_total - memory_used, 0)
            if UNDEFINED not in (memory_total, memory_used)
            else UNDEFINED
        )

        return ProxmoxVMData(
            type=ProxmoxType.QEMU,
            node=node_name,
            status=(
                api_status["lock"]
                if ("lock" in api_status and api_status["lock"] == "suspended")
                else (api_status.get("status", UNDEFINED))
            ),
            locked=bool(api_status.get("lock")),
            guest_file_content=guest_file_content,
            guest_file_path=guest_file_path or UNDEFINED,
            name=api_status.get("name", UNDEFINED),
            health=api_status.get("qmpstatus", UNDEFINED),
            uptime=api_status.get("uptime", UNDEFINED),
            cpu=api_status.get("cpu", UNDEFINED),
            memory_total=memory_total,
            memory_used=memory_used,
            memory_free=memory_free,
            network_in=api_status.get("netin", UNDEFINED),
            network_out=api_status.get("netout", UNDEFINED),
            disk_total=(
                guest_disk_total
                if guest_disk_total is not UNDEFINED
                else api_status.get("maxdisk", UNDEFINED)
            ),
            disk_used=(
                guest_disk_used
                if guest_disk_used is not UNDEFINED
                # From outside, Proxmox cannot see a VM's filesystem: `disk`
                # reports 0 whenever the guest agent does not answer, which is
                # "I cannot tell", not "nothing is used". Reporting it as a
                # measurement produced a confident 0% for guests without a
                # working agent - an OPNsense VM, for instance.
                else _positive_or_undefined(api_status.get("disk", UNDEFINED))
            ),
        )


class ProxmoxLXCCoordinator(ProxmoxCoordinator):
    """Proxmox VE LXC data update coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        proxmox: ProxmoxAPI,
        api_category: str,
        container_id: int,
    ) -> None:
        """Initialize the Proxmox LXC coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name=f"proxmox_coordinator_{api_category}_{container_id}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

        self.hass = hass
        self.config_entry: ConfigEntry = self.config_entry
        self.proxmox = proxmox
        self.node_name: str
        self.resource_id = container_id

    async def _async_update_data(self) -> ProxmoxLXCData:
        """Update data  for Proxmox LXC."""
        node_name = None
        api_status = None

        api_path = "cluster/resources"
        resources = await self.hass.async_add_executor_job(
            poll_api,
            self.hass,
            self.config_entry,
            self.proxmox,
            api_path,
            ProxmoxType.Resources,
            None,
        )

        for resource in resources if resources is not None else []:
            if "vmid" in resource:
                if int(resource["vmid"]) == int(self.resource_id):
                    node_name = resource["node"]

        if node_name is not None:
            api_path = f"nodes/{node_name!s}/lxc/{self.resource_id}/status/current"
            api_status = await self.hass.async_add_executor_job(
                poll_api,
                self.hass,
                self.config_entry,
                self.proxmox,
                api_path,
                ProxmoxType.LXC,
                self.resource_id,
            )
        else:
            msg = f"{self.resource_id} LXC node not found"
            raise UpdateFailed(msg)

        if api_status is None or "status" not in api_status:
            msg = f"LXC {self.resource_id} unable to be found"
            raise UpdateFailed(msg)

        update_device_via(self, ProxmoxType.LXC, node_name)

        return ProxmoxLXCData(
            type=ProxmoxType.LXC,
            node=node_name,
            status=api_status.get("status", UNDEFINED),
            locked=bool(api_status.get("lock")),
            name=api_status.get("name", UNDEFINED),
            uptime=api_status.get("uptime", UNDEFINED),
            cpu=api_status.get("cpu", UNDEFINED),
            memory_total=api_status.get("maxmem", UNDEFINED),
            memory_used=api_status.get("mem", UNDEFINED),
            memory_free=(
                (api_status["maxmem"] - api_status["mem"])
                if ("maxmem" in api_status and "mem" in api_status)
                else UNDEFINED
            ),
            network_in=api_status.get("netin", UNDEFINED),
            network_out=api_status.get("netout", UNDEFINED),
            disk_total=api_status.get("maxdisk", UNDEFINED),
            disk_used=api_status.get("disk", UNDEFINED),
            swap_total=api_status.get("maxswap", UNDEFINED),
            swap_used=api_status.get("swap", UNDEFINED),
            swap_free=(
                (api_status["maxswap"] - api_status["swap"])
                if ("maxswap" in api_status and "swap" in api_status)
                else UNDEFINED
            ),
        )


class ProxmoxStorageCoordinator(ProxmoxCoordinator):
    """Proxmox VE Storage data update coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        proxmox: ProxmoxAPI,
        api_category: str,
        storage_id: str,
    ) -> None:
        """Initialize the Proxmox Storage coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name=f"proxmox_coordinator_{api_category}_{storage_id}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

        self.hass = hass
        self.config_entry: ConfigEntry = self.config_entry
        self.proxmox = proxmox
        self.node_name: str
        self.resource_id = storage_id

    async def _async_update_data(self) -> ProxmoxStorageData:
        """Update data  for Proxmox Update."""
        node_name = None
        api_status = None

        api_path = "cluster/resources"
        resources = await self.hass.async_add_executor_job(
            poll_api,
            self.hass,
            self.config_entry,
            self.proxmox,
            api_path,
            ProxmoxType.Resources,
            None,
        )

        for resource in resources if resources is not None else []:
            if "storage" in resource and resource["id"] == self.resource_id:
                node_name = resource["node"]

        api_path = "cluster/resources?type=storage"
        api_storages = await self.hass.async_add_executor_job(
            poll_api,
            self.hass,
            self.config_entry,
            self.proxmox,
            api_path,
            ProxmoxType.Storage,
            self.resource_id,
        )

        api_status = []
        for api_storage in api_storages:
            if api_storage["id"] == self.resource_id:
                api_status = api_storage

        if api_status is None or "content" not in api_status:
            msg = f"Storage {self.resource_id} unable to be found"
            raise UpdateFailed(msg)

        storage_id = api_status["id"]
        name = f"Storage {storage_id.replace('storage/', '')}"
        return ProxmoxStorageData(
            type=ProxmoxType.Storage,
            node=node_name,
            name=name,
            disk_total=api_status.get("maxdisk", UNDEFINED),
            disk_used=api_status.get("disk", UNDEFINED),
            content=api_status.get("content", UNDEFINED),
        )


class ProxmoxZFSCoordinator(ProxmoxCoordinator):
    """Proxmox VE ZFS data update coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        proxmox: ProxmoxAPI,
        api_category: str,
        node_name: str,
        zfs_id: str,
    ) -> None:
        """Initialize the Proxmox ZFS coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name=f"proxmox_coordinator_{api_category}_{zfs_id}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

        self.hass = hass
        self.config_entry: ConfigEntry = self.config_entry
        self.proxmox = proxmox
        self.node_name = node_name
        self.resource_id = zfs_id

    async def _async_update_data(self) -> ProxmoxStorageData:
        """Update data for Proxmox Update."""
        api_path = f"nodes/{self.node_name}/disks/zfs"
        pools = await self.hass.async_add_executor_job(
            poll_api,
            self.hass,
            self.config_entry,
            self.proxmox,
            api_path,
            ProxmoxType.ZFS,
            self.resource_id,
        )

        pool_status = []
        for pool in pools:
            if pool["name"] == self.resource_id:
                pool_status = pool

        if pool_status is None:
            msg = f"ZFS Pool {self.resource_id} unable to be found for Node {self.node_name}"
            raise UpdateFailed(msg)

        return ProxmoxZFSData(
            type=ProxmoxType.ZFS,
            node=self.node_name,
            name=f"ZFS Pool {self.resource_id}",
            health=pool_status.get("health", UNDEFINED),
            size=pool_status.get("size", UNDEFINED),
            alloc=pool_status.get("alloc", UNDEFINED),
            free=pool_status.get("free", UNDEFINED),
        )


class ProxmoxUpdateCoordinator(ProxmoxCoordinator):
    """Proxmox VE Update data update coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        proxmox: ProxmoxAPI,
        api_category: str,
        node_name: str,
    ) -> None:
        """Initialize the Proxmox Update coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name=f"proxmox_coordinator_{api_category}_{node_name}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

        self.hass = hass
        self.config_entry: ConfigEntry = self.config_entry
        self.proxmox = proxmox
        self.node_name = node_name
        self.resource_id = f"{api_category.capitalize()} {node_name}"

    async def _async_update_data(self) -> ProxmoxUpdateData:
        """Update data  for Proxmox Update."""
        api_path = "nodes"
        node_status = ""
        node_api = {}
        api_status = None
        if nodes_api := await self.hass.async_add_executor_job(
            poll_api,
            self.hass,
            self.config_entry,
            self.proxmox,
            api_path,
            ProxmoxType.Node,
            self.node_name,
        ):
            for node_api in nodes_api:
                if node_api[CONF_NODE] == self.node_name:
                    node_status = node_api["status"]
                    break
            if node_status == "":
                node_status = "offline"
            LOGGER.debug("Node %s status is %s", self.node_name, node_status)

        if node_status == "online":
            if self.node_name is not None:
                api_path = f"nodes/{self.node_name!s}/apt/update"
                api_status = await self.hass.async_add_executor_job(
                    poll_api,
                    self.hass,
                    self.config_entry,
                    self.proxmox,
                    api_path,
                    ProxmoxType.Update,
                    self.resource_id,
                )
            else:
                msg = f"{self.resource_id} node not found"
                raise UpdateFailed(msg)

        if api_status is None:
            return ProxmoxUpdateData(
                type=ProxmoxType.Update,
                node=self.node_name,
                total=UNDEFINED,
                updates_list=UNDEFINED,
                update=UNDEFINED,
            )

        updates_list = []
        for update in api_status:
            updates_list.append(f"{update['Title']} - {update['Version']}")

        updates_list.sort()
        total = len(updates_list) if updates_list is not None else 0
        update_avail = total > 0

        return ProxmoxUpdateData(
            type=ProxmoxType.Update,
            node=self.node_name,
            total=total,
            updates_list=updates_list,
            update=update_avail,
        )


class ProxmoxDiskCoordinator(ProxmoxCoordinator):
    """Proxmox VE Disk data update coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        proxmox: ProxmoxAPI,
        api_category: str,
        node_name: str,
        disk_id: str,
    ) -> None:
        """Initialize the Proxmox Disk coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name=f"proxmox_coordinator_{api_category}_{node_name}_{disk_id}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

        self.hass = hass
        self.config_entry: ConfigEntry = self.config_entry
        self.proxmox = proxmox
        self.node_name = node_name
        self.resource_id = disk_id

    def text_to_smart_id(self, text: str) -> str:
        """Update data  for Proxmox Disk."""
        match text:
            case "Temperature":
                smart_id = "194"
            case "Power Cycles":
                smart_id = "12"
            case "Power On Hours":
                smart_id = "9"
            case _:
                smart_id = "0"
        return smart_id

    async def _async_update_data(self) -> ProxmoxDiskData:
        """Update data  for Proxmox Disk."""
        if self.node_name is not None:
            api_path = f"nodes/{self.node_name}/disks/list"
            api_status = await self.hass.async_add_executor_job(
                poll_api,
                self.hass,
                self.config_entry,
                self.proxmox,
                api_path,
                ProxmoxType.Disk,
                self.resource_id,
            )
        else:
            msg = f"{self.resource_id} node not found"
            raise UpdateFailed(msg)

        if api_status is None:
            return ProxmoxDiskData(
                type=ProxmoxType.Disk,
                node=self.node_name,
                disk_id=self.resource_id,
                path=None,
                disk_wearout=UNDEFINED,
                vendor=None,
                serial=None,
                model=None,
                disk_type=None,
                size=UNDEFINED,
                health=UNDEFINED,
                disk_rpm=UNDEFINED,
                temperature_air=UNDEFINED,
                temperature=UNDEFINED,
                power_cycles=UNDEFINED,
                power_hours=UNDEFINED,
                life_left=UNDEFINED,
                power_loss=UNDEFINED,
                wwn=None,
            )

        for disk in api_status:
            if disk_matches_id(disk, self.resource_id):
                disk_attributes = {}
                api_path = f"nodes/{self.node_name}/disks/smart?disk={disk['devpath']}"
                try:
                    disk_attributes_api = await self.hass.async_add_executor_job(
                        poll_api,
                        self.hass,
                        self.config_entry,
                        self.proxmox,
                        api_path,
                        ProxmoxType.Disk,
                        self.resource_id,
                    )
                except UpdateFailed:
                    disk_attributes_api = None

                attributes_json = []
                if (
                    disk_attributes_api is not None
                    and "attributes" in disk_attributes_api
                ):
                    attributes_json = disk_attributes_api["attributes"]
                elif (
                    disk_attributes_api is not None
                    and "type" in disk_attributes_api
                    and disk_attributes_api["type"] == "text"
                ):
                    attributes_text = disk_attributes_api["text"].split("\n")
                    for value_text in attributes_text:
                        value_json = value_text.split(":")
                        if len(value_json) >= 2:
                            attributes_json.append(
                                {
                                    "name": value_json[0].strip(),
                                    "raw": value_json[1].strip().replace(",", ""),
                                    "id": self.text_to_smart_id(value_json[0].strip()),
                                }
                            )

                for disk_attribute in attributes_json:
                    if int(disk_attribute["id"].strip()) == 12:
                        disk_attributes["power_cycles"] = int(disk_attribute["raw"])

                    elif int(disk_attribute["id"].strip()) == 194:
                        disk_attributes["temperature"] = int(
                            disk_attribute["raw"].strip().split(" ", 1)[0]
                        )

                    elif int(disk_attribute["id"].strip()) == 190:
                        disk_attributes["temperature_air"] = int(
                            disk_attribute["raw"].strip().split(" ", 1)[0]
                        )

                    elif int(disk_attribute["id"].strip()) == 9:
                        power_hours_raw = disk_attribute["raw"]
                        if len(power_hours_h := power_hours_raw.strip().split("h")) > 1:
                            disk_attributes["power_hours"] = int(
                                power_hours_h[0].strip()
                            )
                        elif (
                            len(power_hours_s := power_hours_raw.strip().split(" ")) > 1
                        ):
                            disk_attributes["power_hours"] = int(
                                power_hours_s[0].strip()
                            )
                        else:
                            disk_attributes["power_hours"] = int(disk_attribute["raw"])

                    elif int(disk_attribute["id"].strip()) == 231:
                        disk_attributes["life_left"] = int(disk_attribute["value"])

                    elif int(disk_attribute["id"].strip()) == 174:
                        disk_attributes["power_loss"] = int(disk_attribute["raw"])

                disk_type = disk.get("type", None)
                return ProxmoxDiskData(
                    type=ProxmoxType.Disk,
                    node=self.node_name,
                    disk_id=self.resource_id,
                    path=disk["devpath"],
                    vendor=disk.get("vendor", None),
                    serial=disk.get("serial", None),
                    model=disk.get("model", None),
                    disk_type=disk_type,
                    wwn=disk.get("wwn", None),
                    disk_wearout=(
                        float(disk["wearout"])
                        if (
                            "wearout" in disk
                            and disk_type.upper() in ("SSD", "NVME")
                            and str(disk["wearout"]).upper() != "N/A"
                        )
                        else UNDEFINED
                    ),
                    size=float(disk["size"]) if "size" in disk else UNDEFINED,
                    health=disk.get("health", UNDEFINED),
                    disk_rpm=(
                        float(disk["rpm"])
                        if (
                            "rpm" in disk
                            and disk_type.upper() not in ("SSD", "NVME", "USB", None)
                        )
                        else UNDEFINED
                    ),
                    temperature_air=disk_attributes.get("temperature_air", UNDEFINED),
                    temperature=disk_attributes.get("temperature", UNDEFINED),
                    power_cycles=disk_attributes.get("power_cycles", UNDEFINED),
                    life_left=disk_attributes.get("life_left", UNDEFINED),
                    power_hours=disk_attributes.get("power_hours", UNDEFINED),
                    power_loss=disk_attributes.get("power_loss", UNDEFINED),
                )

        msg = f"Disk {self.resource_id} not found on node {self.node_name}."
        raise UpdateFailed(msg)


class ProxmoxTaskCoordinator(ProxmoxCoordinator):
    """Proxmox VE Task data update coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        proxmox: ProxmoxAPI,
        api_category: str,
        node_name: str,
    ) -> None:
        """Initialize the Proxmox Task coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name=f"proxmox_coordinator_{api_category}_{node_name}",
            update_interval=timedelta(seconds=300),  # 5 minutes
        )

        self.hass = hass
        self.config_entry: ConfigEntry = self.config_entry
        self.proxmox = proxmox
        self.node_name = node_name
        self.resource_id = node_name

    async def _async_update_data(self) -> ProxmoxTaskData:
        """Update data for Proxmox Tasks."""
        if self.node_name is not None:
            api_path = f"nodes/{self.node_name}/tasks"
            api_status = await self.hass.async_add_executor_job(
                poll_api,
                self.hass,
                self.config_entry,
                self.proxmox,
                api_path,
                ProxmoxType.Tasks,
                self.resource_id,
            )
        else:
            msg = f"{self.resource_id} node not found"
            raise UpdateFailed(msg)

        if api_status is None:
            return ProxmoxTaskData(
                type=ProxmoxType.Tasks,
                node=self.node_name,
                failed_count=0,
                recent_failures=UNDEFINED,
                last_failure_time=UNDEFINED,
            )

        # Filter for failed tasks in the last 24 hours (86400 seconds)
        current_time = int(time.time())
        twenty_four_hours_ago = current_time - 86400

        failed_tasks = []
        for task in api_status:
            # Task is considered failed if:
            # 1. status is not "OK" (for completed tasks)
            # 2. status is not "running" (for active tasks)
            # 3. starttime is within last 24 hours
            task_status = task.get("status", "")
            task_starttime = int(task.get("starttime", 0))
            task_endtime = int(task.get("endtime", 0))

            if (
                task_status not in ("OK", "running")
                and task_starttime > twenty_four_hours_ago
                and task_status != ""  # Ignore tasks with empty status
            ):
                # Convert timestamps to readable dates in Home Assistant's timezone
                tz = ZoneInfo(str(self.hass.config.time_zone))
                starttime_str = datetime.fromtimestamp(task_starttime, tz=tz).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                endtime_str = (
                    datetime.fromtimestamp(task_endtime, tz=tz).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    if task_endtime > 0
                    else "N/A"
                )

                failed_tasks.append(
                    {
                        "type": task.get("type", "unknown"),
                        "starttime": starttime_str,
                        "endtime": endtime_str,
                        "status": task_status,
                    }
                )

        # Sort by start time (most recent first) and limit to 10 recent failures
        failed_tasks.sort(key=lambda x: x["starttime"], reverse=True)
        recent_failures = failed_tasks[:10] if failed_tasks else UNDEFINED
        last_failure_time = failed_tasks[0]["endtime"] if failed_tasks else UNDEFINED

        return ProxmoxTaskData(
            type=ProxmoxType.Tasks,
            node=self.node_name,
            failed_count=len(failed_tasks),
            recent_failures=recent_failures,
            last_failure_time=last_failure_time,
        )


def update_device_via(
    self,
    api_category: ProxmoxType,
    node_name: str,
) -> None:
    """Return the Device Info."""
    dev_reg = dr.async_get(self.hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=self.config_entry.entry_id,
        identifiers={
            (
                DOMAIN,
                f"{self.config_entry.entry_id}_{api_category.upper()}_{self.resource_id}",
            )
        },
    )
    # Scoped to this config entry: identifiers are only unique within one, so
    # async_get_device can resolve to a device belonging to a different
    # integration that happens to share the pair.
    via_device = dev_reg.async_get_device_by_identifier(
        (
            DOMAIN,
            f"{self.config_entry.entry_id}_{ProxmoxType.Node.upper()}_{node_name}",
        ),
        self.config_entry.entry_id,
    )
    via_device_id: str | UndefinedType = via_device.id if via_device else UNDEFINED
    if device.via_device_id != via_device_id:
        LOGGER.debug(
            "Update device %s - connected via device: old=%s, new=%s",
            self.resource_id,
            device.via_device_id,
            via_device_id,
        )
        dev_reg.async_update_device(
            device.id,
            via_device_id=via_device_id,
            entry_type=dr.DeviceEntryType.SERVICE,
        )


# Keyword-only arguments are not an option here: every caller reaches this
# through `hass.async_add_executor_job(poll_api, ...)`, which forwards its
# arguments positionally and accepts no keywords.
def poll_api(  # noqa: PLR0917
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    proxmox: ProxmoxAPI,
    api_path: str,
    api_category: ProxmoxType,
    resource_id: str | int | None = None,
    *,
    issue_crete_permissions: bool | None = True,
) -> dict[str, Any] | None:
    """Return data from the Proxmox Node API."""

    def permission_to_resource(
        api_category: ProxmoxType,
        resource_id: int | str | None = None,
    ) -> str:
        """Return the permissions required for the resource."""
        match api_category:
            case ProxmoxType.Node:
                return f"['perm','/nodes/{resource_id}',['Sys.Audit']]"
            case ProxmoxType.QEMU | ProxmoxType.LXC:
                return f"['perm','/vms/{resource_id}',['VM.Audit']]"
            case ProxmoxType.Storage:
                return f"['perm','/storage/{resource_id}',['Datastore.Audit'],'any',1]"
            case ProxmoxType.Update:
                return f"['perm','/nodes/{resource_id}',['Sys.Modify']]"
            case ProxmoxType.Disk:
                return f"['perm','/nodes/{resource_id}',['Sys.Audit']]"
            case ProxmoxType.Tasks:
                return f"['perm','/nodes/{resource_id}',['Sys.Audit']]"
            case ProxmoxType.Proxmox:
                return "['perm','/',['Sys.Audit']]"
            case _:
                return "Unmapped"

    try:
        api_data = get_api(proxmox, api_path)
    except AuthenticationError as error:
        raise ConfigEntryAuthFailed from error
    except (
        SSLError,
        ConnectTimeout,
        HTTPError,
        ConnectionError,
        connError,
        RetryError,
    ) as error:
        raise UpdateFailed(error) from error
    except ResourceException as error:
        if error.status_code == 403 and issue_crete_permissions:
            ir.create_issue(
                hass,
                DOMAIN,
                f"{config_entry.entry_id}_{resource_id}_forbiden",
                is_fixable=False,
                is_persistent=True,
                severity=ir.IssueSeverity.ERROR,
                translation_key="resource_exception_forbiden",
                translation_placeholders={
                    "resource": f"{api_category.capitalize()} {resource_id.replace(f'{ProxmoxType.Update.capitalize()} ', '')}",
                    "user": (
                        config_entry.data.get(CONF_HA_ADMIN_USERNAME)
                        if api_category is ProxmoxType.Proxmox
                        else config_entry.data[CONF_USERNAME]
                    ),
                    "permission": permission_to_resource(
                        api_category,
                        resource_id.replace(f"{ProxmoxType.Update.capitalize()} ", ""),
                    ),
                },
            )
            LOGGER.debug(
                f"Error get API path {api_path}: User not allowed to access the resource, check user permissions as per the documentation, see details in the repair created by the integration."
            )
            return None
        raise UpdateFailed from error
    ir.delete_issue(
        hass,
        DOMAIN,
        f"{config_entry.entry_id}_{resource_id}_forbiden",
    )
    return api_data
