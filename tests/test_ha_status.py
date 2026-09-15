# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for the Proxmox VE cluster HA status entities."""

import dataclasses
from types import SimpleNamespace
from unittest.mock import MagicMock

import homeassistant.util.dt as dt_util
from homeassistant.helpers.typing import UNDEFINED

from custom_components.proxmoxve.binary_sensor import (
    PROXMOX_BINARYSENSOR_HA_STATUS,
    ProxmoxBinarySensorEntity,
)
from custom_components.proxmoxve.const import ProxmoxType
from custom_components.proxmoxve.coordinator import HA_ARMED_STATES, parse_ha_status
from custom_components.proxmoxve.models import ProxmoxHAStatusData
from custom_components.proxmoxve.sensor import (
    PROXMOX_SENSOR_HA_STATUS,
    ProxmoxSensorEntity,
    ProxmoxSensorEntityDescription,
)

MASTER_TIMESTAMP = 1767225600

# Shape of `GET /cluster/ha/status/current` on a cluster running a
# pve-ha-manager with arm/disarm support, currently disarmed in freeze mode
# with one container in error.
STATUS_CURRENT = [
    {
        "id": "quorum",
        "type": "quorum",
        "node": "pve1",
        "status": "OK",
        "quorate": 1,
    },
    {
        "id": "master",
        "type": "master",
        "node": "pve1",
        "status": "pve1 (active, Wed Dec 31 00:00:00 2025)",
        "timestamp": MASTER_TIMESTAMP,
    },
    {
        "id": "fencing",
        "type": "fencing",
        "node": "pve1",
        "status": "disarmed, resource mode: freeze (CRM watchdog released)",
        "armed-state": "disarmed",
        "resource_mode": "freeze",
    },
    {
        "id": "lrm:pve1",
        "type": "lrm",
        "node": "pve1",
        "status": "pve1 (idle, watchdog standby, Wed Dec 31 00:00:01 2025)",
        "timestamp": MASTER_TIMESTAMP + 1,
    },
    {
        "id": "service:vm:100",
        "type": "service",
        "sid": "vm:100",
        "node": "pve1",
        "state": "started",
        "crm_state": "started",
        "request_state": "started",
    },
    {
        "id": "service:ct:105",
        "type": "service",
        "sid": "ct:105",
        "node": "pve2",
        "state": "error",
        "crm_state": "error",
        "request_state": "started",
    },
]


def _description(key: str) -> ProxmoxSensorEntityDescription:
    """Return the HA status sensor description with the given key."""
    return next(
        description
        for description in PROXMOX_SENSOR_HA_STATUS
        if description.key == key
    )


def _sensor(key: str, data: SimpleNamespace) -> ProxmoxSensorEntity:
    """Build an HA status sensor backed by the given coordinator data."""
    coordinator = MagicMock()
    coordinator.data = data
    return ProxmoxSensorEntity(
        coordinator=coordinator,
        unique_id=f"test_{key}",
        info_device={},
        description=_description(key),
    )


def test_parse_ha_status() -> None:
    """Test the HA status parser reads every structured field."""
    data = parse_ha_status(STATUS_CURRENT)

    assert data.type == ProxmoxType.Proxmox
    assert data.armed_state == "disarmed"
    assert data.resource_mode == "freeze"
    assert data.quorate is True
    assert data.crm_master == "pve1"
    assert data.crm_master_last_seen == dt_util.utc_from_timestamp(MASTER_TIMESTAMP)
    assert data.ha_resources_total == 2
    assert data.ha_resources_error == 1
    assert data.ha_resources_error_list == [
        {"sid": "ct:105", "node": "pve2", "crm_state": "error"}
    ]
    # The fixture timestamp is far in the past, so the master reads as dead.
    assert data.crm_master_stale is True


def test_parse_ha_status_fresh_master_is_not_stale() -> None:
    """Test a master that just refreshed its timestamp is not stale."""
    entries = [
        {**entry, "timestamp": dt_util.utcnow().timestamp() - 5}
        if entry["type"] == "master"
        else entry
        for entry in STATUS_CURRENT
    ]

    assert parse_ha_status(entries).crm_master_stale is False


def test_parse_ha_status_stale_master() -> None:
    """Test a master past the 30 s Proxmox itself treats as dead."""
    entries = [
        {**entry, "timestamp": dt_util.utcnow().timestamp() - 31}
        if entry["type"] == "master"
        else entry
        for entry in STATUS_CURRENT
    ]

    assert parse_ha_status(entries).crm_master_stale is True


def test_parse_ha_status_unusable_timestamp_has_no_staleness() -> None:
    """Test a timestamp that cannot be read yields no staleness at all."""
    entries = [
        {**entry, "timestamp": "not-a-timestamp"}
        if entry["type"] == "master"
        else entry
        for entry in STATUS_CURRENT
    ]

    data = parse_ha_status(entries)

    assert data.crm_master_last_seen is UNDEFINED
    assert data.crm_master_stale is UNDEFINED


def test_crm_master_last_seen_is_disabled_by_default() -> None:
    """Test the constantly-changing timestamp is not created by default."""
    assert _description("crm_master_last_seen").entity_registry_enabled_default is False


def test_parse_ha_status_without_fencing_entry() -> None:
    """Test a cluster without arm/disarm support reports no armed state."""
    entries = [entry for entry in STATUS_CURRENT if entry["type"] != "fencing"]

    data = parse_ha_status(entries)

    assert data.armed_state is UNDEFINED
    assert data.resource_mode is None
    assert data.quorate is True


def test_parse_ha_status_ignores_unknown_armed_state() -> None:
    """Test an unknown armed state is dropped instead of breaking the enum."""
    entries = [
        {**entry, "armed-state": "something-new"}
        if entry["type"] == "fencing"
        else entry
        for entry in STATUS_CURRENT
    ]

    assert parse_ha_status(entries).armed_state is UNDEFINED


def test_parse_ha_status_no_quorum() -> None:
    """Test a cluster that lost quorum is reported as not quorate."""
    entries = [
        {**entry, "quorate": 0, "status": "No quorum on node 'pve1'!"}
        if entry["type"] == "quorum"
        else entry
        for entry in STATUS_CURRENT
    ]

    assert parse_ha_status(entries).quorate is False


def test_parse_ha_status_empty() -> None:
    """Test an empty status keeps the counters at zero."""
    data = parse_ha_status([])

    assert data.ha_resources_total == 0
    assert data.ha_resources_error == 0
    assert data.ha_resources_error_list == []
    assert data.crm_master is UNDEFINED
    assert data.crm_master_last_seen is UNDEFINED


def test_descriptions_match_the_data_model() -> None:
    """Test every described key and attribute exists on the HA status model."""
    fields = {field.name for field in dataclasses.fields(ProxmoxHAStatusData)}

    for description in (*PROXMOX_SENSOR_HA_STATUS, *PROXMOX_BINARYSENSOR_HA_STATUS):
        assert description.key in fields
        for attribute in getattr(description, "extra_attrs", None) or []:
            assert attribute in fields


def test_armed_state_sensor_options_match_parser() -> None:
    """Test the enum sensor accepts exactly the states the parser can emit."""
    assert set(_description("armed_state").options) == HA_ARMED_STATES


def test_armed_state_sensor_value_and_attributes() -> None:
    """Test the armed state sensor exposes the resource mode as an attribute."""
    sensor = _sensor(
        "armed_state",
        SimpleNamespace(armed_state="disarming", resource_mode="ignore"),
    )

    assert sensor.native_value == "disarming"
    assert sensor.extra_state_attributes == {"resource_mode": "ignore"}


def test_resources_error_sensor_reports_zero() -> None:
    """Test a healthy cluster reports 0 rather than an unknown state."""
    sensor = _sensor(
        "ha_resources_error",
        SimpleNamespace(ha_resources_error=0, ha_resources_error_list=[]),
    )

    assert sensor.native_value == 0
    assert sensor.extra_state_attributes == {"ha_resources_error_list": []}


def _binary_sensor(key: str, data: SimpleNamespace) -> ProxmoxBinarySensorEntity:
    """Build an HA status binary sensor backed by the given coordinator data."""
    description = next(
        candidate
        for candidate in PROXMOX_BINARYSENSOR_HA_STATUS
        if candidate.key == key
    )
    coordinator = MagicMock()
    coordinator.data = data
    return ProxmoxBinarySensorEntity(
        coordinator=coordinator,
        unique_id=f"test_{key}",
        info_device={},
        description=description,
    )


def test_quorate_binary_sensor() -> None:
    """Test the quorate binary sensor follows the parsed quorum state."""
    assert _binary_sensor("quorate", SimpleNamespace(quorate=True)).is_on is True
    assert _binary_sensor("quorate", SimpleNamespace(quorate=False)).is_on is False


def test_crm_master_stale_binary_sensor() -> None:
    """Test the stale binary sensor reports a problem only when stale."""
    stale = SimpleNamespace(crm_master_stale=True)
    alive = SimpleNamespace(crm_master_stale=False)

    assert _binary_sensor("crm_master_stale", stale).is_on is True
    assert _binary_sensor("crm_master_stale", alive).is_on is False
