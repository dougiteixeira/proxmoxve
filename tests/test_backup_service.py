# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for starting a backup from Home Assistant, and seeing it run."""

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from proxmoxer.core import ResourceException
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.proxmoxve import DOMAIN
from custom_components.proxmoxve.coordinator import parse_backup, parse_running_backup
from custom_components.proxmoxve.services import SERVICE_BACKUP, vzdump_parameters

from .fake_api import NODE, FakeProxmox
from .test_setup_full import _setup, _state

# What `tasks?source=active&typefilter=vzdump` lists while a run is on.
RUNNING = [
    {
        "type": "vzdump",
        "id": "101",
        "starttime": 1_789_470_000,
        "status": "running",
        "user": "root@pam",
        "upid": "UPID:pve:0022399A:011DCC6B:6AA92530:vzdump:101:root@pam:",
    }
]


def test_parameters_for_named_guests() -> None:
    """Test the guest ids become the comma list vzdump wants."""
    params = vzdump_parameters(
        {"vmid": [100, 101], "mode": "snapshot", "storage": "local", "compress": "zstd"}
    )

    assert params == {
        "vmid": "100,101",
        "mode": "snapshot",
        "storage": "local",
        "compress": "zstd",
    }


def test_parameters_for_everything_on_the_node() -> None:
    """Test 'all' wins over any ids named alongside it."""
    params = vzdump_parameters({"vmid": [100], "all": True, "mode": "stop"})

    assert params == {"all": 1, "mode": "stop"}


def test_naming_nothing_is_a_mistake() -> None:
    """Test neither guests nor 'all' is refused rather than backing up nothing."""
    with pytest.raises(ServiceValidationError):
        vzdump_parameters({"mode": "snapshot"})


def test_a_run_in_progress_is_described() -> None:
    """Test the active task list yields the running flag, start and guests."""
    running = parse_running_backup(RUNNING)

    assert running["running"] is True
    assert running["running_guests"] == "101"
    assert running["running_since"].timestamp() == 1_789_470_000
    assert parse_running_backup([]) == {
        "running": False,
        "running_since": None,
        "running_guests": None,
    }
    assert parse_running_backup("nonsense")["running"] is False


def test_the_backup_data_carries_the_run_in_progress() -> None:
    """Test a node with no finished run yet still reports one in progress."""
    data = parse_backup([], NODE, RUNNING)

    assert data.runs == 0
    assert data.running is True
    assert data.running_guests == "101"


async def test_the_service_starts_a_backup_and_returns_the_task(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test the call posts to vzdump with the parameters and hands back the UPID."""
    await _setup(hass, current_entry)

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_BACKUP,
        {"node": NODE, "vmid": [101], "storage": "local", "mode": "snapshot"},
        blocking=True,
        return_response=True,
    )

    posts = [call for call in fake_api.calls if call[0] == "POST"]
    assert posts, "nothing was posted"
    _, path, data, params = posts[-1]
    assert path == f"nodes/{NODE}/vzdump"
    sent = {**(data or {}), **(params or {})}
    assert sent == {"vmid": "101", "mode": "snapshot", "storage": "local"}
    assert response["upid"].startswith("UPID:")
    assert response["node"] == NODE


async def test_the_service_refuses_a_node_nobody_tracks(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test a node no entry tracks is a validation error, not a silent no-op."""
    await _setup(hass, current_entry)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, SERVICE_BACKUP, {"node": "elsewhere", "all": True}, blocking=True
        )


async def test_a_refusal_by_proxmox_reaches_the_caller(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test a 403 - VM.Backup missing, say - comes back as an error with its text."""
    await _setup(hass, current_entry)
    fake_api.post_error = ResourceException(
        403, "Permission check failed", "(/vms/101, [VM.Backup])"
    )

    with pytest.raises(HomeAssistantError, match=r"VM\.Backup"):
        await hass.services.async_call(
            DOMAIN, SERVICE_BACKUP, {"node": NODE, "vmid": [101]}, blocking=True
        )


async def test_the_node_shows_a_backup_running(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test the binary sensor is on while the active task list has a vzdump."""
    fake_api.routes[f"nodes/{NODE}/tasks?typefilter=vzdump&source=active&limit=1"] = (
        RUNNING
    )
    await _setup(hass, current_entry)
    entry_id = current_entry.entry_id

    state = _state(
        hass, current_entry, f"{entry_id}_backup_{NODE}_running", "binary_sensor"
    )
    assert state.state == "on"
    assert state.attributes["running_guests"] == "101"


async def test_the_node_shows_no_backup_running_when_the_list_is_empty(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test the sensor exists and is off when nothing runs."""
    fake_api.routes[f"nodes/{NODE}/tasks?typefilter=vzdump&source=active&limit=1"] = []
    await _setup(hass, current_entry)
    entry_id = current_entry.entry_id

    state = _state(
        hass, current_entry, f"{entry_id}_backup_{NODE}_running", "binary_sensor"
    )
    assert state.state == "off"
