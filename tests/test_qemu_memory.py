# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for how a QEMU guest's memory usage is read."""

from homeassistant.helpers.typing import UNDEFINED

from custom_components.proxmoxve.coordinator import qemu_memory_used

# Trimmed from `pvesh get /nodes/<node>/qemu/118/status/current` on a Linux
# guest whose balloon driver reports statistics. Note that total_mem minus
# free_mem is exactly `mem`, and that `memhost` sits above both.
GUEST_WITH_BALLOON_STATS = {
    "agent": 1,
    "balloon": 6442450944,
    "ballooninfo": {
        "actual": 6442450944,
        "free_mem": 100392960,
        "max_mem": 6442450944,
        "total_mem": 6212415488,
    },
    "maxmem": 6442450944,
    "mem": 6112022528,
    "memhost": 6394974208,
}

# The same call for a guest without a balloon driver (OPNsense). ballooninfo
# carries no guest numbers at all, and `mem` is then identical to `memhost` -
# the host-side resident size of the QEMU process.
GUEST_WITHOUT_BALLOON_STATS = {
    "agent": 1,
    "balloon": 12884901888,
    "ballooninfo": {"actual": 12884901888, "max_mem": 12884901888},
    "maxmem": 12884901888,
    "mem": 10253205504,
    "memhost": 10253205504,
}


def test_guest_numbers_are_preferred() -> None:
    """Test the guest's own figure is used when the balloon driver reports it."""
    assert qemu_memory_used(GUEST_WITH_BALLOON_STATS) == 6112022528


def test_guest_numbers_match_what_proxmox_derives() -> None:
    """Test the formula reproduces `mem` where Proxmox already derives it."""
    assert qemu_memory_used(GUEST_WITH_BALLOON_STATS) == GUEST_WITH_BALLOON_STATS["mem"]


def test_falls_back_to_mem_without_balloon_stats() -> None:
    """Test `mem` is used when the guest reports nothing of its own."""
    assert qemu_memory_used(GUEST_WITHOUT_BALLOON_STATS) == 10253205504


def test_host_side_figure_no_longer_exceeds_the_configured_memory() -> None:
    """
    Test the reported bug: a percentage above 100%.

    Proxmox hands out the host-side size in `mem`, which carries emulator
    overhead and can sit above the configured memory. Where the guest reports
    its own numbers they win, so the ratio stays within bounds.
    """
    api_status = {
        "ballooninfo": {
            "actual": 4294967296,
            "free_mem": 590558003,
            "max_mem": 4294967296,
            "total_mem": 4294967296,
        },
        "maxmem": 4294967296,
        "mem": 4321378304,  # above maxmem - the host-side figure
    }

    used = qemu_memory_used(api_status)

    assert used == 3704409293
    assert used < api_status["maxmem"]


def test_missing_ballooninfo() -> None:
    """Test a response without ballooninfo at all still reports something."""
    assert qemu_memory_used({"maxmem": 1024, "mem": 512}) == 512


def test_unusable_ballooninfo_values() -> None:
    """Test nonsensical balloon numbers are ignored rather than trusted."""
    assert qemu_memory_used({"ballooninfo": "nonsense", "mem": 512}) == 512
    assert (
        qemu_memory_used({"ballooninfo": {"total_mem": "a", "free_mem": 1}, "mem": 512})
        == 512
    )
    # free_mem above total_mem cannot be right; fall back rather than go negative.
    assert (
        qemu_memory_used({"ballooninfo": {"total_mem": 10, "free_mem": 20}, "mem": 512})
        == 512
    )


def test_nothing_to_report() -> None:
    """Test a response carrying no memory figure at all yields UNDEFINED."""
    assert qemu_memory_used({"maxmem": 1024}) is UNDEFINED
