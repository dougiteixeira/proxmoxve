# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for a node's most recent backup run."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import homeassistant.util.dt as dt_util
from homeassistant.const import EntityCategory
from homeassistant.helpers.typing import UNDEFINED

from custom_components.proxmoxve.binary_sensor import (
    PROXMOX_BINARYSENSOR_BACKUP,
    ProxmoxBinarySensorEntity,
)
from custom_components.proxmoxve.const import ProxmoxType
from custom_components.proxmoxve.coordinator import parse_backup
from custom_components.proxmoxve.sensor import (
    PROXMOX_SENSOR_BACKUP,
    ProxmoxSensorEntity,
)

STARTED = 1767225600
FINISHED = STARTED + 1234

# Shaped like `GET /nodes/<node>/tasks?typefilter=vzdump&limit=1`: the newest
# finished backup task. The real entry also carries `upid`, `pid` and
# `pstart`, none of which are read. Values here are invented.
BACKUP_OK = [
    {
        "upid": "UPID:pve1:00001234:0000ABCD:69554B80:vzdump:100,101:root@pam:",
        "node": "pve1",
        "type": "vzdump",
        "id": "100,101",
        "user": "root@pam",
        "starttime": STARTED,
        "endtime": FINISHED,
        "status": "OK",
    }
]

BACKUP_WITH_ERRORS = [{**BACKUP_OK[0], "status": "job errors"}]

# A job that backs up every guest on the node has an empty id.
BACKUP_ALL = [{**BACKUP_OK[0], "id": ""}]


def _sensor(key: str, data: object) -> ProxmoxSensorEntity:
    """Build a backup sensor over the given coordinator data."""
    coordinator = MagicMock()
    coordinator.data = data
    description = next(d for d in PROXMOX_SENSOR_BACKUP if d.key == key)
    return ProxmoxSensorEntity(
        coordinator=coordinator,
        unique_id=f"test_{key}",
        info_device={},
        description=description,
    )


def _binary_sensor(data: object) -> ProxmoxBinarySensorEntity:
    """Build the backup problem sensor over the given coordinator data."""
    coordinator = MagicMock()
    coordinator.data = data
    return ProxmoxBinarySensorEntity(
        coordinator=coordinator,
        unique_id="test_backup_failed",
        info_device={},
        description=PROXMOX_BINARYSENSOR_BACKUP[0],
    )


def test_parse_a_successful_run() -> None:
    """Test the newest finished run is described in full."""
    data = parse_backup(BACKUP_OK, "pve1")

    assert data.type == ProxmoxType.Backup
    assert data.node == "pve1"
    assert data.runs == 1
    assert data.started == dt_util.utc_from_timestamp(STARTED)
    assert data.finished == dt_util.utc_from_timestamp(FINISHED)
    assert data.duration == 1234
    assert data.status == "OK"
    assert data.guests == "100,101"
    assert data.user == "root@pam"


def test_parse_a_run_covering_everything() -> None:
    """Test an empty guest list reads as none rather than an empty string."""
    assert parse_backup(BACKUP_ALL, "pve1").guests is None


def test_parse_without_any_run() -> None:
    """Test a node that never ran a backup has nothing to report."""
    data = parse_backup([], "pve1")

    assert data.runs == 0
    assert data.finished is UNDEFINED
    assert data.duration is UNDEFINED
    assert data.status is None


def test_parse_ignores_other_task_types() -> None:
    """Test a stray non-backup task in the answer does not count."""
    data = parse_backup([{**BACKUP_OK[0], "type": "qmstart"}], "pve1")

    assert data.runs == 0


def test_parse_without_an_end_time() -> None:
    """Test a task with no end time yields no duration, but still a start."""
    entry = {key: value for key, value in BACKUP_OK[0].items() if key != "endtime"}
    data = parse_backup([entry], "pve1")

    assert data.started == dt_util.utc_from_timestamp(STARTED)
    assert data.finished is UNDEFINED
    assert data.duration is UNDEFINED


def test_sensors_report_the_run() -> None:
    """Test the timestamp and the duration reach the sensors."""
    data = parse_backup(BACKUP_OK, "pve1")

    assert _sensor("finished", data).native_value == dt_util.utc_from_timestamp(
        FINISHED
    )
    assert _sensor("duration", data).native_value == 1234
    assert _sensor("finished", data).extra_state_attributes == {
        "status": "OK",
        "guests": "100,101",
        "user": "root@pam",
    }


def test_problem_sensor_follows_the_verdict() -> None:
    """Test anything but OK is a problem - including partial failures."""
    assert _binary_sensor(parse_backup(BACKUP_OK, "pve1")).is_on is False
    assert _binary_sensor(parse_backup(BACKUP_WITH_ERRORS, "pve1")).is_on is True
    assert (
        _binary_sensor(SimpleNamespace(status="unexpected status", runs=1)).is_on
        is True
    )


def test_defaults_match_the_core_integration() -> None:
    """Test all three are diagnostic and off, as in the core integration."""
    for description in (*PROXMOX_SENSOR_BACKUP, *PROXMOX_BINARYSENSOR_BACKUP):
        assert description.entity_registry_enabled_default is False
        assert description.entity_category is EntityCategory.DIAGNOSTIC
