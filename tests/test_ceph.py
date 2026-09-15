# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for reading a Ceph cluster's health."""

from homeassistant.helpers.typing import UNDEFINED

from custom_components.proxmoxve.coordinator import CEPH_HEALTH_STATES, parse_ceph
from custom_components.proxmoxve.sensor import PROXMOX_SENSOR_CEPH

# `GET /cluster/ceph/status` hands through what `ceph -s` reports, so the
# shape comes from Ceph rather than a Proxmox schema. The real response also
# carries the monitor, OSD and placement group maps. Values here are invented.
HEALTHY = {
    "fsid": "00000000-0000-0000-0000-000000000000",
    "health": {"status": "HEALTH_OK", "checks": {}},
    "osdmap": {"num_osds": 6},
}
DEGRADED = {
    "health": {
        "status": "HEALTH_WARN",
        "checks": {
            "OSD_DOWN": {
                "severity": "HEALTH_WARN",
                "summary": {"message": "1 osds down"},
            },
            "PG_DEGRADED": {
                "severity": "HEALTH_WARN",
                "summary": {"message": "Degraded data redundancy"},
            },
        },
    },
}


def test_a_healthy_cluster() -> None:
    """Test the good case reports ok and nothing to look at."""
    data = parse_ceph(HEALTHY)

    assert data.health == "ok"
    assert data.checks == []


def test_a_degraded_cluster_lists_what_is_wrong() -> None:
    """Test each failing check is carried with its message."""
    data = parse_ceph(DEGRADED)

    assert data.health == "warning"
    assert data.checks == [
        {
            "check": "OSD_DOWN",
            "severity": "HEALTH_WARN",
            "message": "1 osds down",
        },
        {
            "check": "PG_DEGRADED",
            "severity": "HEALTH_WARN",
            "message": "Degraded data redundancy",
        },
    ]


def test_an_error_state() -> None:
    """Test the worst state maps through as well."""
    assert parse_ceph({"health": {"status": "HEALTH_ERR"}}).health == "error"


def test_an_unknown_health_state_is_dropped() -> None:
    """Test a state Ceph might add later never reaches the enum."""
    assert parse_ceph({"health": {"status": "HEALTH_FUTURE"}}).health is UNDEFINED


def test_responses_without_a_health_block() -> None:
    """Test a response shaped differently still yields a usable result."""
    assert parse_ceph({}).health is UNDEFINED
    assert parse_ceph({"health": "not a dict"}).health is UNDEFINED
    assert parse_ceph({"health": {}}).checks == []


def test_malformed_checks_are_skipped() -> None:
    """Test a check that is not an object does not break the list."""
    data = parse_ceph({"health": {"status": "HEALTH_WARN", "checks": "nonsense"}})

    assert data.health == "warning"
    assert data.checks == []


def test_a_check_without_a_message() -> None:
    """Test a check still appears when it carries no summary."""
    data = parse_ceph({"health": {"status": "HEALTH_WARN", "checks": {"X": {}}}})

    assert data.checks == [{"check": "X"}]


def test_sensor_options_match_the_parser() -> None:
    """Test the enum sensor accepts exactly the states the parser can emit."""
    assert set(PROXMOX_SENSOR_CEPH[0].options) == set(CEPH_HEALTH_STATES.values())


def test_the_attribute_stays_serializable() -> None:
    """Test the check list holds only values Home Assistant can store."""
    for check in parse_ceph(DEGRADED).checks:
        for key, value in check.items():
            assert isinstance(key, str)
            assert isinstance(value, str)
