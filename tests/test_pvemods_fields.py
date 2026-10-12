# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""
Tests for reading PVE-mods, whichever of its three payloads a node sends.

PVE-mods renamed the field twice and changed its shape once, and all three
versions are installed out there. Reported upstream in #706 by someone
whose sensors went quiet after upgrading to v2: the integration only knew
the oldest name.

Every structure below was measured on a live node by installing v1.0.7,
v2.0.0 and v2.1.1 in turn and reading `GET /nodes/{node}/status`, with
only `[lm_sensors] enabled=1` and `enable_cpu=1` switched on.
"""

from __future__ import annotations

from typing import Any

from custom_components.proxmoxve.coordinator import (
    SENSOR_FIELDS,
    _parse_sensors_dict,
    _readings_of,
)

# v1.0.7 and v2.0.0: the chips sit under `data` in a named block, and a
# reading is a flat number under the label it carries.
OLD_SHAPE: dict[str, Any] = {
    "cpu": True,
    "cpu_temp_target": "Core",
    "fans": False,
    "ignore_temp_below": 5,
    "temp_unit": "C",
    "data": {
        "PVE MOD lm-sensors Enhanced": {
            "acpitz-acpi-0": {
                "Adapter": "ACPI interface",
                "temp1": {"temp1_input": 35},
            },
            "coretemp-isa-0000": {
                "Adapter": "ISA adapter",
                "cpu_model": "Intel(R) Celeron(R) CPU N3450 @ 1.10GHz",
                "cpu_package": "0",
                "Package id 0": {
                    "temp1_input": 36,
                    "temp1_max": 105,
                    "temp1_crit": 105,
                    "temp1_crit_alarm": 0,
                },
                "Core 0": {"temp2_input": 35, "temp2_max": 105},
                "Core 3": {"temp5_input": 34, "temp5_max": 105},
            },
        }
    },
}

# v2.1.1: the chips sit under `enhanced_sensors`, keyed by the raw sensor
# id, and a reading became an object with its own unit.
NEW_SHAPE: dict[str, Any] = {
    "cpu": True,
    "cpu_temp_target": "Core",
    "display_zero_speed_fans": False,
    "ram": False,
    "temp_unit": "C",
    "enhanced_sensors": {
        "acpitz-acpi-0": {
            "Adapter": "ACPI interface",
            "temp1": {"input": {"quantity": "temperature", "unit": "C", "value": 35}},
        },
        "coretemp-isa-0000": {
            "Adapter": "ISA adapter",
            "cpu_model": "Intel(R) Celeron(R) CPU N3450 @ 1.10GHz",
            "cpu_package": "0",
            "temp1": {
                "label": "Package id 0",
                "input": {"quantity": "temperature", "unit": "C", "value": 36},
                "max": {"quantity": "temperature", "unit": "C", "value": 105},
                "crit_alarm": {"quantity": "boolean", "value": 0},
            },
            "temp2": {
                "label": "Core 0",
                "input": {"quantity": "temperature", "unit": "C", "value": 35},
            },
            "temp5": {
                "label": "Core 3",
                "input": {"quantity": "temperature", "unit": "C", "value": 34},
            },
        },
    },
}


def test_the_three_field_names_are_all_known() -> None:
    """Test the names PVE-mods has used, newest first."""
    assert SENSOR_FIELDS == (
        "PveMods_SensorInfo",
        "PveMods_JsonSensorInfo",
        "PveMod_JsonSensorInfo",
    )


def test_the_older_payload_is_read_from_its_block() -> None:
    """Test the shape v1.0.7 and v2.0.0 share."""
    readings = _parse_sensors_dict(_readings_of(OLD_SHAPE))

    assert readings == {
        "acpitz-acpi-0 temp1": 35.0,
        "coretemp-isa-0000 Package id 0": 36.0,
        "coretemp-isa-0000 Core 0": 35.0,
        "coretemp-isa-0000 Core 3": 34.0,
    }


def test_the_newer_payload_yields_the_same_names() -> None:
    """
    Test v2.1.1 reads as the same sensors, not as new ones.

    The entity ids and the history hang on these names, so a PVE-mods
    upgrade must not rename `coretemp-isa-0000 Package id 0` into
    `coretemp-isa-0000 temp1` - which is what the raw ids would give.
    """
    readings = _parse_sensors_dict(_readings_of(NEW_SHAPE))

    assert readings == {
        "acpitz-acpi-0 temp1": 35.0,
        "coretemp-isa-0000 Package id 0": 36.0,
        "coretemp-isa-0000 Core 0": 35.0,
        "coretemp-isa-0000 Core 3": 34.0,
    }


def test_a_sensor_without_a_label_keeps_its_id() -> None:
    """Test the id stands in where the newer payload carries no label."""
    readings = _parse_sensors_dict(
        _readings_of(
            {
                "enhanced_sensors": {
                    "nct6798-isa-0290": {
                        "fan2": {"input": {"quantity": "fan", "value": 1150}}
                    }
                }
            }
        )
    )

    assert readings == {"nct6798-isa-0290 fan2": 1150.0}


def test_an_idle_collector_yields_nothing_rather_than_nonsense() -> None:
    """
    Test the switches alone are not mistaken for readings.

    PVE-mods tears its collection down after ten seconds of inactivity, so
    a poll can arrive with the field present, the switches in it, and no
    chips at all. That is the case the readings are held over, not one to
    parse something out of.
    """
    assert _readings_of({"cpu": True, "temp_unit": "C"}) == {}
    assert _readings_of({"data": {}}) == {}
    assert _readings_of({"data": {"PVE MOD lm-sensors Enhanced": {}}}) == {}
    assert _readings_of({"enhanced_sensors": {}}) == {}
    assert _readings_of({"disabled": True}) == {}


def test_nonsense_is_not_an_exception() -> None:
    """Test a payload shaped like nothing we know reads as no readings."""
    assert _readings_of({"data": "a string"}) == {}
    assert _readings_of({"enhanced_sensors": [1, 2, 3]}) == {}
    assert _readings_of({"enhanced_sensors": {"chip": "not a dict"}}) == {}
    assert _readings_of({"enhanced_sensors": {"chip": {"temp1": {"input": 36}}}}) == {}
