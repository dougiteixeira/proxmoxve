# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for the noise suppression on counter-derived timestamp sensors."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.proxmoxve.sensor import (
    PROXMOX_SENSOR_UPTIME,
    ProxmoxSensorEntity,
)

LAST_BOOT = PROXMOX_SENSOR_UPTIME[0]


def _sensor() -> tuple[ProxmoxSensorEntity, MagicMock]:
    """Return a Last boot sensor and the coordinator feeding it."""
    coordinator = MagicMock()
    sensor = ProxmoxSensorEntity(
        coordinator=coordinator,
        unique_id="test_last_boot",
        info_device={},
        description=LAST_BOOT,
    )
    return sensor, coordinator


def test_last_boot_ignores_second_level_jitter() -> None:
    """
    Test a boot time that only wobbles keeps its published value.

    The API reports whole seconds, so `utcnow() - uptime` lands a second or
    two apart on every poll while the machine keeps running. Reporting each
    of those would record a state change once per update interval.
    """
    sensor, coordinator = _sensor()

    coordinator.data = SimpleNamespace(uptime=100_000)
    first = sensor.native_value

    for uptime in (100_001, 99_998, 100_002):
        coordinator.data = SimpleNamespace(uptime=uptime)
        assert sensor.native_value == first


def test_last_boot_follows_a_real_reboot() -> None:
    """Test a reboot moves the value past the margin and is reported."""
    sensor, coordinator = _sensor()

    coordinator.data = SimpleNamespace(uptime=100_000)
    before = sensor.native_value

    coordinator.data = SimpleNamespace(uptime=30)
    after = sensor.native_value

    assert after != before
    assert after > before


def test_last_boot_without_uptime() -> None:
    """Test an uptime of zero reports nothing rather than a bogus time."""
    sensor, coordinator = _sensor()

    coordinator.data = SimpleNamespace(uptime=0)

    assert sensor.native_value is None
