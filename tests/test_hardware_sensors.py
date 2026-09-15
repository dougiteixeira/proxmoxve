# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for holding hardware readings across a gap in the source data."""

from datetime import timedelta

import homeassistant.util.dt as dt_util

from custom_components.proxmoxve.coordinator import (
    SENSORS_HOLD_FOR,
    ProxmoxNodeCoordinator,
)

READINGS = {"coretemp-isa-0000 Package id 0": 57.0, "acpitz-acpi-0 temp1": 38.0}
LATER = {"coretemp-isa-0000 Package id 0": 61.0, "acpitz-acpi-0 temp1": 39.0}


def _coordinator() -> ProxmoxNodeCoordinator:
    """
    Build a coordinator without touching Home Assistant.

    Only the three attributes the hold uses are needed, and constructing the
    real thing would drag in a config entry and an event loop for a decision
    that is pure bookkeeping.
    """
    coordinator = object.__new__(ProxmoxNodeCoordinator)
    coordinator.resource_id = "node1"
    coordinator._last_sensors = {}  # noqa: SLF001
    coordinator._last_sensors_raw = None  # noqa: SLF001
    coordinator._last_sensors_at = None  # noqa: SLF001
    return coordinator


def test_readings_are_passed_through_and_remembered() -> None:
    """Test a poll that brings readings uses them and keeps them."""
    coordinator = _coordinator()

    sensors, raw = coordinator._hold_last_sensors(READINGS, "raw")  # noqa: SLF001

    assert sensors == READINGS
    assert raw == "raw"
    assert coordinator._last_sensors == READINGS  # noqa: SLF001


def test_a_gap_keeps_the_previous_readings() -> None:
    """
    Test one poll without readings does not blank the sensors.

    PVE-mods collects on demand, so the file the API handler reads is only
    there while something keeps asking for it. The field arrives empty
    whenever a poll gets in first. Reporting nothing puts a hole in the
    history where the truth is "not this time".
    """
    coordinator = _coordinator()
    coordinator._hold_last_sensors(READINGS, "raw")  # noqa: SLF001

    sensors, raw = coordinator._hold_last_sensors({}, None)  # noqa: SLF001

    assert sensors == READINGS
    assert raw == "raw"


def test_new_readings_replace_the_held_ones() -> None:
    """Test the hold never wins over an actual reading."""
    coordinator = _coordinator()
    coordinator._hold_last_sensors(READINGS, "raw")  # noqa: SLF001
    coordinator._hold_last_sensors({}, None)  # noqa: SLF001

    sensors, _ = coordinator._hold_last_sensors(LATER, "raw2")  # noqa: SLF001

    assert sensors == LATER


def test_readings_are_dropped_once_they_are_stale() -> None:
    """
    Test the hold gives up rather than showing a temperature forever.

    Past the limit whatever provides the data is gone rather than late -
    PVE-mods removed, the module unloaded - and reporting nothing is then
    the honest answer.
    """
    coordinator = _coordinator()
    coordinator._hold_last_sensors(READINGS, "raw")  # noqa: SLF001
    coordinator._last_sensors_at = (  # noqa: SLF001
        dt_util.utcnow() - SENSORS_HOLD_FOR - timedelta(seconds=1)
    )

    sensors, raw = coordinator._hold_last_sensors({}, None)  # noqa: SLF001

    assert sensors == {}
    assert raw is None
    assert coordinator._last_sensors_at is None  # noqa: SLF001


def test_a_gap_before_any_reading() -> None:
    """Test a node that never reported readings holds nothing."""
    coordinator = _coordinator()

    sensors, raw = coordinator._hold_last_sensors({}, None)  # noqa: SLF001

    assert sensors == {}
    assert raw is None
