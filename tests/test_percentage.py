# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for turning a ratio into a percentage a dashboard can trust."""

from typing import Any

from homeassistant.helpers.typing import UNDEFINED

from custom_components.proxmoxve.sensor import (
    PROXMOX_SENSOR_MEMORY,
    ProxmoxSensorEntityDescription,
    percentage_or_unknown,
)


def _description(key: str) -> ProxmoxSensorEntityDescription:
    """Find one sensor description by its key."""
    return next(d for d in PROXMOX_SENSOR_MEMORY if d.key == key)


def test_a_normal_ratio() -> None:
    """Test the ordinary case is a plain multiplication."""
    assert percentage_or_unknown(0.5) == 50
    assert percentage_or_unknown(1) == 100


def test_no_reading_stays_unknown() -> None:
    """Test a missing figure is not reported as 0%."""
    assert percentage_or_unknown(None) is None
    assert percentage_or_unknown(UNDEFINED) is None


def test_zero_is_a_reading() -> None:
    """Test an actual zero is kept, unlike a missing one."""
    assert percentage_or_unknown(0) == 0


def test_a_ratio_above_one_is_capped() -> None:
    """
    Test the reported bug: a memory sensor showing 106%.

    A QEMU guest whose balloon driver reports no statistics leaves Proxmox
    with only the host-side size of the QEMU process. That carries emulator
    overhead and can sit above the configured memory, so the ratio leaves
    the range where it still describes how full the guest is.
    """
    assert percentage_or_unknown(1.06) == 100
    assert percentage_or_unknown(4.2) == 100


def test_a_negative_ratio_is_floored() -> None:
    """Test nothing below zero reaches a percentage sensor."""
    assert percentage_or_unknown(-0.2) == 0


class _Data:
    """Stand-in for the guest data a sensor description reads."""

    def __init__(self, used: Any, total: Any, free: Any) -> None:
        self.memory_used = used
        self.memory_total = total
        self.memory_free = free


def test_the_memory_sensors_go_through_the_cap() -> None:
    """
    Test the memory percentages use the shared conversion.

    They each carried their own lambda, which neither capped the ratio nor
    kept a missing reading unknown - which is how 106% got out.
    """
    used = _description("memory_used_perc")
    free = _description("memory_free_perc")

    assert used.conversion_fn is percentage_or_unknown
    assert free.conversion_fn is percentage_or_unknown


def test_a_host_side_figure_reports_full_rather_than_more() -> None:
    """Test the values behind the 106% now land on 100%."""
    description = _description("memory_used_perc")
    # 4 GiB configured, host-side figure a little above it.
    data = _Data(used=4321378304, total=4294967296, free=0)

    ratio = description.value_fn(data)

    assert ratio > 1
    assert description.conversion_fn(ratio) == 100


def test_a_guest_without_memory_figures() -> None:
    """Test a guest reporting nothing yields unknown, not 0%."""
    description = _description("memory_used_perc")
    data = _Data(used=UNDEFINED, total=UNDEFINED, free=UNDEFINED)

    assert description.value_fn(data) is None
    assert description.conversion_fn(description.value_fn(data)) is None


def test_a_stopped_guest_still_reports_zero() -> None:
    """
    Test a guest that is off reads 0%, not unknown.

    Its memory total is still configured and its usage really is nothing, so
    this is a measurement rather than an absence of one.
    """
    description = _description("memory_used_perc")
    data = _Data(used=0, total=4294967296, free=4294967296)

    assert description.conversion_fn(description.value_fn(data)) == 0
