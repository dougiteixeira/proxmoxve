# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for reporting a QEMU guest's disk usage honestly."""

from homeassistant.helpers.typing import UNDEFINED

from custom_components.proxmoxve.coordinator import _positive_or_undefined
from custom_components.proxmoxve.sensor import percentage_or_unknown


def test_zero_from_the_api_is_not_a_measurement() -> None:
    """
    Test `disk: 0` is treated as no reading rather than an empty disk.

    Proxmox cannot see a VM's filesystem from outside, so it reports 0
    whenever the guest agent does not answer - an OPNsense guest, for
    instance. Taken at face value that became a confident "0% used".
    """
    assert _positive_or_undefined(0) is UNDEFINED


def test_a_real_reading_survives() -> None:
    """Test a usable figure is passed through untouched."""
    assert _positive_or_undefined(34359738368) == 34359738368


def test_missing_and_nonsense_values() -> None:
    """Test anything that is not a positive number reads as no value."""
    assert _positive_or_undefined(UNDEFINED) is UNDEFINED
    assert _positive_or_undefined(None) is UNDEFINED
    assert _positive_or_undefined(-1) is UNDEFINED
    assert _positive_or_undefined("42") is UNDEFINED
    # A bool is an int in Python, but it is not a byte count.
    truthy = True
    assert _positive_or_undefined(truthy) is UNDEFINED


def test_percentage_keeps_unknown_unknown() -> None:
    """Test a missing ratio reports nothing instead of 0%."""
    assert percentage_or_unknown(None) is None
    assert percentage_or_unknown(UNDEFINED) is None


def test_percentage_converts_a_ratio() -> None:
    """Test a real ratio still becomes a percentage."""
    assert percentage_or_unknown(0.5) == 50
    assert percentage_or_unknown(1) == 100


def test_percentage_of_zero_is_still_zero() -> None:
    """Test a genuine zero ratio stays 0%, unlike a missing one."""
    assert percentage_or_unknown(0) == 0
