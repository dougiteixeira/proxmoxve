# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for reading a node's replication health."""

from homeassistant.helpers.typing import UNDEFINED

from custom_components.proxmoxve.coordinator import parse_replication

# Shaped like `GET /nodes/<node>/replication`. The real entries also carry
# `schedule`, `type`, `source`, `last_try`, `duration`, `pid` and `next_sync`.
# Values here are invented.
HEALTHY = {
    "id": "101-0",
    "guest": 101,
    "target": "node2",
    "last_sync": 1_700_000_000,
    "fail_count": 0,
}
BEHIND = {
    "id": "205-0",
    "guest": 205,
    "target": "node3",
    "last_sync": 1_600_000_000,
    "fail_count": 0,
}
FAILING = {
    "id": "300-0",
    "guest": 300,
    "vmtype": "lxc",
    "target": "node2",
    "last_sync": 1_500_000_000,
    "fail_count": 4,
    "error": "target node is not online",
}


# The complete field set a healthy job actually returns, from a live PVE 9
# cluster - node names and the guest id replaced. Note what is *absent*: a
# job that is neither disabled nor failing carries no `disable` and no
# `error` key at all.
LIVE_HEALTHY = {
    "duration": 13.585964,
    "fail_count": 0,
    "guest": 9999,
    "id": "9999-1",
    "jobnum": 1,
    "last_sync": 1_788_858_902,
    "last_try": 1_788_858_902,
    "next_sync": 1_791_032_400,
    "schedule": "sat *-1..7 15:00",
    "source": "node-a",
    "target": "node-b",
    "type": "local",
    "vmtype": "lxc",
}


def test_a_real_healthy_job() -> None:
    """
    Test the exact shape a live cluster returns for a job that is fine.

    The keys this does *not* contain are the point: no `disable`, no `error`.
    Reading either without a default would fail on every healthy job.
    """
    data = parse_replication([LIVE_HEALTHY], "node-a")

    assert data.jobs == 1
    assert data.failing is False
    assert data.failing_jobs == []
    assert data.oldest_sync.timestamp() == 1_788_858_902


def test_no_jobs() -> None:
    """Test a node without replication reports nothing to act on."""
    data = parse_replication([], "node1")

    assert data.jobs == 0
    assert data.failing is False
    assert data.oldest_sync is UNDEFINED
    assert data.failing_jobs == []


def test_healthy_jobs() -> None:
    """Test jobs that are keeping up raise no alarm."""
    data = parse_replication([HEALTHY, BEHIND], "node1")

    assert data.jobs == 2
    assert data.failing is False
    assert data.failing_jobs == []


def test_the_oldest_sync_wins() -> None:
    """
    Test the furthest-behind job decides the reported time.

    The newest would hide a job that stopped replicating days ago, which is
    the case worth seeing.
    """
    data = parse_replication([HEALTHY, BEHIND], "node1")

    assert data.oldest_sync.timestamp() == 1_600_000_000


def test_a_failing_job_is_reported_with_its_error() -> None:
    """Test the failure is flagged and says which job and why."""
    data = parse_replication([HEALTHY, FAILING], "node1")

    assert data.failing is True
    assert data.failing_jobs == [
        {
            "id": "300-0",
            "failures": 4,
            "guest": 300,
            "guest_type": "lxc",
            "target": "node2",
            "error": "target node is not online",
        }
    ]


def test_disabled_jobs_are_counted_but_stay_quiet() -> None:
    """
    Test a job somebody turned off does not raise the alarm.

    It is still counted, so the entity exists and says the node has jobs.
    """
    data = parse_replication([{**FAILING, "disable": 1}], "node1")

    assert data.jobs == 1
    assert data.failing is False
    assert data.failing_jobs == []
    assert data.oldest_sync is UNDEFINED


def test_a_job_that_never_synced() -> None:
    """Test a job with no successful sync yet does not invent a time."""
    data = parse_replication([{"id": "400-0", "guest": 400, "fail_count": 0}], "node1")

    assert data.jobs == 1
    assert data.oldest_sync is UNDEFINED


def test_malformed_entries_are_skipped() -> None:
    """Test anything without an id is not counted as a job."""
    data = parse_replication(["nonsense", {"guest": 1}, HEALTHY], "node1")

    assert data.jobs == 1


def test_the_attribute_stays_serializable() -> None:
    """Test the failing job list holds only values Home Assistant can store."""
    data = parse_replication([FAILING], "node1")

    for job in data.failing_jobs:
        for key, value in job.items():
            assert isinstance(key, str)
            assert isinstance(value, (str, int))
