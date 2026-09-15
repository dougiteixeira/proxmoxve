# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for reading a disk's SMART attributes."""

from custom_components.proxmoxve.coordinator import (
    _leading_int,
    parse_smart_attributes,
)

# Shaped like the `attributes` list of `nodes/<node>/disks/smart` for an ATA
# drive: smartctl's numbered attributes, each with a raw and a normalised
# value. Values are invented.
ATA = [
    {"id": "9", "name": "Power_On_Hours", "raw": "20707", "value": "97"},
    {"id": "12", "name": "Power_Cycle_Count", "raw": "782", "value": "100"},
    {"id": "190", "name": "Airflow_Temperature_Cel", "raw": "38", "value": "62"},
    {
        "id": "194",
        "name": "Temperature_Celsius",
        "raw": "41 (Min/Max 20/45)",
        "value": "41",
    },
    {"id": "231", "name": "SSD_Life_Left", "raw": "0", "value": "97"},
    {"id": "174", "name": "Unexpect_Power_Loss_Ct", "raw": "127", "value": "100"},
]


def test_the_common_attributes_are_read() -> None:
    """Test each attribute the sensors show is picked up by its SMART id."""
    assert parse_smart_attributes(ATA) == {
        "power_hours": 20707,
        "power_cycles": 782,
        "temperature_air": 38,
        "temperature": 41,
        "life_left": 97,
        "power_loss": 127,
    }


def test_a_temperature_the_drive_does_not_have() -> None:
    """
    Test the reported bug: a virtual NVMe reports its temperature as `-`.

    `int("-")` took the whole disk coordinator down and marked every entity
    of that disk unavailable, for one field the drive simply does not have.
    The temperature is now left out and the rest is still read.
    """
    attributes = [
        {"id": "194", "name": "Temperature", "raw": "-"},
        {"id": "12", "name": "Power Cycles", "raw": "0"},
        {"id": "9", "name": "Power On Hours", "raw": "0"},
    ]

    assert parse_smart_attributes(attributes) == {"power_cycles": 0, "power_hours": 0}


def test_power_on_hours_in_every_shape_smartctl_uses() -> None:
    """Test the hour count survives the suffixes drives put on it."""
    for raw in ("3728", "3728h+12m+30.5s", "3728 (150 22 0)", "3,728"):
        assert parse_smart_attributes([{"id": "9", "raw": raw}]) == {
            "power_hours": 3728
        }


def test_attributes_that_are_not_wanted_are_ignored() -> None:
    """Test an id the sensors do not show contributes nothing."""
    assert parse_smart_attributes([{"id": "5", "raw": "0"}]) == {}


def test_malformed_entries_are_skipped() -> None:
    """Test nothing shaped wrongly can stop the rest from being read."""
    attributes = [
        "nonsense",
        {"raw": "41"},
        {"id": "abc", "raw": "41"},
        {"id": "194"},
        {"id": "194", "raw": None},
        {"id": "12", "raw": "782"},
    ]

    assert parse_smart_attributes(attributes) == {"power_cycles": 782}


def test_leading_int() -> None:
    """Test the number in front is what counts, and its absence is None."""
    assert _leading_int("41 (Min/Max 20/45)") == 41
    assert _leading_int("  7 ") == 7
    assert _leading_int(9) == 9
    assert _leading_int("-") is None
    assert _leading_int("") is None
    assert _leading_int(None) is None
    assert _leading_int(True) is None  # noqa: FBT003 - a bool is not a count
    assert _leading_int(["41"]) is None
