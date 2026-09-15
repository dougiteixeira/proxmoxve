# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for reading a disk's SMART attributes."""

from custom_components.proxmoxve.coordinator import (
    _leading_int,
    parse_smart_attributes,
    parse_smart_text,
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


# The `text` form of `nodes/<node>/disks/smart`, as Proxmox hands it out for
# an NVMe drive: the health log, no attribute ids. Trimmed; values invented.
NVME_TEXT = """
SMART/Health Information (NVMe Log 0x02, NSID 0x1)
Critical Warning:                   0x00
Temperature:                        43 Celsius
Available Spare:                    100%
Percentage Used:                    4%
Data Units Read:                    49,025,812 [25.1 TB]
Power Cycles:                       1,381
Power On Hours:                     3,728
Unsafe Shutdowns:                   317
Temperature Sensor 1:               43 Celsius
Temperature Sensor 2:               51 Celsius
"""

# The same call for a SAS drive behind an expander (a NetApp shelf). Other
# words for the same three things, and a label with a colon of its own.
SAS_TEXT = """
=== START OF READ SMART DATA SECTION ===
SMART Health Status: OK

Current Drive Temperature:     27 C
Drive Trip Temperature:        85 C

Manufactured in week 15 of year 2013
Specified cycle count over device lifetime:  50000
Accumulated start-stop cycles:  48
Specified load-unload count over device lifetime:  600000
Accumulated load-unload cycles:  3667
Elements in grown defect list: 0

Background scan results log
  Status: no scans active
    Accumulated power on time, hours:minutes 27473:19 [1648399 minutes]
    Number of background scans performed: 0,  scan progress: 0.00%
"""


def test_the_nvme_health_log() -> None:
    """Test the three values the sensors show are read from the NVMe text."""
    assert parse_smart_attributes(parse_smart_text(NVME_TEXT)) == {
        "temperature": 43,
        "power_cycles": 1381,
        "power_hours": 3728,
    }


def test_a_second_temperature_sensor_does_not_pass_for_the_first() -> None:
    """Test `Temperature Sensor 2` is not taken for `Temperature`."""
    text = "Temperature Sensor 2:   51 Celsius\nTemperature:  43 Celsius\n"

    assert parse_smart_attributes(parse_smart_text(text)) == {"temperature": 43}


def test_a_sas_drive_behind_an_expander() -> None:
    """
    Test the reported gap: SAS drives showed no SMART values at all.

    smartctl uses different labels for SAS, and the power-on time label
    carries a colon itself, which the old split on the first colon cut in
    half - the value then read `minutes 27473`, which is not a number.
    """
    assert parse_smart_attributes(parse_smart_text(SAS_TEXT)) == {
        "temperature": 27,
        "power_cycles": 48,
        "power_hours": 27473,
    }


def test_text_without_any_known_label() -> None:
    """Test unrelated text yields no attributes rather than nonsense."""
    assert parse_smart_text("SMART Health Status: OK\nno colon here\n") == []
