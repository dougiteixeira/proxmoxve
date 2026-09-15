# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for the status enum sensors of nodes, VMs and containers."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.helpers.typing import UNDEFINED

from custom_components.proxmoxve.sensor import (
    LXC_STATES,
    NODE_STATES,
    PROXMOX_SENSOR_LXC,
    PROXMOX_SENSOR_NODES,
    PROXMOX_SENSOR_QEMU,
    QEMU_STATES,
    ProxmoxSensorEntity,
    ProxmoxSensorEntityDescription,
    qemu_status,
)

ENGLISH = json.loads(
    (
        Path(__file__).parent.parent
        / "custom_components"
        / "proxmoxve"
        / "translations"
        / "en.json"
    ).read_text(encoding="utf-8")
)


def _description(
    descriptions: tuple[ProxmoxSensorEntityDescription, ...],
) -> ProxmoxSensorEntityDescription:
    """Return the status sensor description out of a platform's tuple."""
    return next(d for d in descriptions if d.key == "status_raw")


def _sensor(
    description: ProxmoxSensorEntityDescription, data: SimpleNamespace
) -> ProxmoxSensorEntity:
    """Build a status sensor over the given coordinator data."""
    coordinator = MagicMock()
    coordinator.data = data
    return ProxmoxSensorEntity(
        coordinator=coordinator,
        unique_id="test_status",
        info_device={},
        description=description,
    )


def test_a_running_vm() -> None:
    """Test the plain case reads from `status`."""
    assert qemu_status(SimpleNamespace(status="running", health="running")) == "running"


def test_qemu_run_state_wins_when_it_says_more() -> None:
    """Test a paused VM is reported paused, not running."""
    assert qemu_status(SimpleNamespace(status="running", health="paused")) == "paused"


def test_a_hibernated_vm_reads_suspended() -> None:
    """
    Test the lock-derived status survives.

    A VM suspended to disk is stopped as far as QEMU is concerned; the
    coordinator turns the `suspended` lock into the status, and that is the
    more useful answer.
    """
    assert (
        qemu_status(SimpleNamespace(status="suspended", health="stopped"))
        == "suspended"
    )


def test_without_a_run_state() -> None:
    """Test a VM whose qmpstatus is missing falls back to `status`."""
    assert qemu_status(SimpleNamespace(status="stopped", health=UNDEFINED)) == "stopped"


def test_a_state_this_integration_has_never_heard_of() -> None:
    """
    Test an unknown state becomes unknown rather than an error.

    A value outside the declared options makes Home Assistant refuse the
    whole state update; reporting unknown loses less.
    """
    assert qemu_status(SimpleNamespace(status="running", health="teleporting")) is None


def test_node_status_is_normalized() -> None:
    """Test the capitalised placeholder the coordinator uses for an offline node."""
    description = _description(PROXMOX_SENSOR_NODES)

    assert _sensor(description, SimpleNamespace(status="Offline")).native_value == (
        "offline"
    )
    assert _sensor(description, SimpleNamespace(status="online")).native_value == (
        "online"
    )


def test_container_status() -> None:
    """Test a container is running or stopped and nothing else."""
    description = _description(PROXMOX_SENSOR_LXC)

    assert _sensor(description, SimpleNamespace(status="stopped")).native_value == (
        "stopped"
    )
    assert _sensor(description, SimpleNamespace(status="mounted")).native_value is None


@pytest.mark.parametrize(
    ("descriptions", "states"),
    [
        (PROXMOX_SENSOR_QEMU, QEMU_STATES),
        (PROXMOX_SENSOR_LXC, LXC_STATES),
        (PROXMOX_SENSOR_NODES, NODE_STATES),
    ],
)
def test_status_sensors_are_enums(
    descriptions: tuple[ProxmoxSensorEntityDescription, ...],
    states: tuple[str, ...],
) -> None:
    """Test each status sensor declares exactly the states its parser emits."""
    description = _description(descriptions)

    assert description.device_class is SensorDeviceClass.ENUM
    assert tuple(description.options) == states


@pytest.mark.parametrize(
    "descriptions",
    [PROXMOX_SENSOR_QEMU, PROXMOX_SENSOR_LXC, PROXMOX_SENSOR_NODES],
)
def test_every_status_has_an_english_name(
    descriptions: tuple[ProxmoxSensorEntityDescription, ...],
) -> None:
    """Test no state would show up untranslated."""
    description = _description(descriptions)
    translated = ENGLISH["entity"]["sensor"][description.translation_key]["state"]

    assert set(description.options) <= set(translated)


def test_only_the_guest_status_is_on_by_default() -> None:
    """Test the node's enum stays off: its binary sensor already says online."""
    assert _description(PROXMOX_SENSOR_QEMU).entity_registry_enabled_default is True
    assert _description(PROXMOX_SENSOR_LXC).entity_registry_enabled_default is True
    assert _description(PROXMOX_SENSOR_NODES).entity_registry_enabled_default is False
