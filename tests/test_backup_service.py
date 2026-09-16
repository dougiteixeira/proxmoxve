# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for starting a backup from Home Assistant, and seeing it run."""

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from proxmoxer.core import ResourceException
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.proxmoxve import DOMAIN
from custom_components.proxmoxve.const import CONF_BACKUP_STORAGE
from custom_components.proxmoxve.coordinator import parse_backup, parse_running_backup
from custom_components.proxmoxve.services import (
    SERVICE_BACKUP,
    BackupPlan,
    vzdump_parameters,
)

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


def _plan(**kwargs) -> BackupPlan:  # noqa: ANN003
    entry = MockConfigEntry(domain=DOMAIN, options=kwargs.pop("options", {}))
    return BackupPlan(entry, kwargs.pop("node", NODE), **kwargs)


def test_parameters_for_named_guests() -> None:
    """Test the guest ids become the comma list vzdump wants, in order."""
    params = vzdump_parameters(
        {"mode": "snapshot", "storage": "local", "compress": "zstd"},
        _plan(vmids={101, 100}),
    )

    assert params == {
        "vmid": "100,101",
        "mode": "snapshot",
        "storage": "local",
        "compress": "zstd",
    }


def test_parameters_for_everything_on_the_node() -> None:
    """Test everything on the node wins over any ids planned alongside it."""
    params = vzdump_parameters({"mode": "stop"}, _plan(vmids={100}, everything=True))

    assert params == {"all": 1, "mode": "stop"}


def test_the_storage_falls_back_to_the_buttons_option() -> None:
    """Test a call without a storage writes where the backup buttons write."""
    plan = _plan(vmids={100}, options={CONF_BACKUP_STORAGE: "nas"})

    assert vzdump_parameters({}, plan)["storage"] == "nas"
    assert vzdump_parameters({"storage": "elsewhere"}, plan)["storage"] == "elsewhere"
    assert "storage" not in vzdump_parameters({}, _plan(vmids={100}))


def test_notes_need_a_storage() -> None:
    """
    Test a notes template without a storage is refused before the call.

    `pvesh usage /nodes/<node>/vzdump` says `--notes-template` requires
    `storage`; sending it alone gets a parameter error from Proxmox. The
    storage from the options counts.
    """
    with pytest.raises(ServiceValidationError):
        vzdump_parameters({"notes": "{{guestname}}"}, _plan(vmids={100}))

    params = vzdump_parameters(
        {"storage": "backups", "notes": "{{guestname}}"}, _plan(vmids={100})
    )
    assert params["notes-template"] == "{{guestname}}"
    params = vzdump_parameters(
        {"notes": "{{guestname}}"},
        _plan(vmids={100}, options={CONF_BACKUP_STORAGE: "nas"}),
    )
    assert params["notes-template"] == "{{guestname}}"


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
    assert response["skipped"] == []
    (run,) = response["runs"]
    assert run["upid"].startswith("UPID:")
    assert run["node"] == NODE


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


def _device(hass: HomeAssistant, entry: MockConfigEntry, identifier: str) -> str:
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{entry.entry_id}_{identifier}"), entry.entry_id
    )
    assert device is not None, identifier
    return device.id


def _posts(fake_api: FakeProxmox) -> list[tuple[str, dict]]:
    return [
        (path, {**(data or {}), **(params or {})})
        for method, path, data, params in fake_api.calls
        if method == "POST"
    ]


async def test_naming_nothing_is_a_mistake(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test no target, no guest, no node and no 'all' is refused, not a no-op."""
    await _setup(hass, current_entry)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, SERVICE_BACKUP, {"mode": "snapshot"}, blocking=True
        )
    assert _posts(fake_api) == []


async def test_a_guest_device_as_target_finds_its_node(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """
    Test targeting guest devices is enough - node and storage are looked up.

    The VM's and the container's devices are the target; the node comes
    from their coordinators, the storage from the buttons' option.
    """
    hass.config_entries.async_update_entry(
        current_entry, options={**current_entry.options, CONF_BACKUP_STORAGE: "ext"}
    )
    await _setup(hass, current_entry)

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_BACKUP,
        {
            "device_id": [
                _device(hass, current_entry, "QEMU_101"),
                _device(hass, current_entry, "LXC_100"),
            ]
        },
        blocking=True,
        return_response=True,
    )

    assert _posts(fake_api) == [
        (
            f"nodes/{NODE}/vzdump",
            {"vmid": "100,101", "mode": "snapshot", "storage": "ext"},
        )
    ]
    assert [run["node"] for run in response["runs"]] == [NODE]


async def test_a_node_device_as_target_backs_up_everything_on_it(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test a node device means every guest it hosts, like the button."""
    await _setup(hass, current_entry)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_BACKUP,
        {"device_id": _device(hass, current_entry, f"NODE_{NODE}"), "mode": "stop"},
        blocking=True,
    )

    assert _posts(fake_api) == [(f"nodes/{NODE}/vzdump", {"all": 1, "mode": "stop"})]


async def test_the_cluster_device_as_target_runs_on_every_node(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test the cluster device means one run per tracked node."""
    await _setup(hass, current_entry)

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_BACKUP,
        {"device_id": _device(hass, current_entry, "cluster")},
        blocking=True,
        return_response=True,
    )

    assert [path for path, _ in _posts(fake_api)] == [f"nodes/{NODE}/vzdump"]
    assert response["runs"][0]["all"] == 1


async def test_an_entity_as_target_counts_for_its_device(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test a guest's entity picks the guest, as targets do everywhere."""
    await _setup(hass, current_entry)
    entity_id = er.async_get(hass).async_get_entity_id(
        "binary_sensor", DOMAIN, f"{current_entry.entry_id}_101_status"
    )
    assert entity_id is not None

    await hass.services.async_call(
        DOMAIN, SERVICE_BACKUP, {"entity_id": entity_id}, blocking=True
    )

    assert _posts(fake_api) == [
        (f"nodes/{NODE}/vzdump", {"vmid": "101", "mode": "snapshot"})
    ]


async def test_guest_ids_alone_are_looked_up_to_their_node(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test `vmid` without a node works; an unknown id is refused."""
    await _setup(hass, current_entry)

    await hass.services.async_call(
        DOMAIN, SERVICE_BACKUP, {"vmid": [100, 101]}, blocking=True
    )
    assert _posts(fake_api) == [
        (f"nodes/{NODE}/vzdump", {"vmid": "100,101", "mode": "snapshot"})
    ]

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, SERVICE_BACKUP, {"vmid": [999]}, blocking=True
        )


async def test_a_storage_device_cannot_be_backed_up(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test a storage device as target is refused with a message, not posted."""
    await _setup(hass, current_entry)

    with pytest.raises(ServiceValidationError, match="cannot be backed up"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_BACKUP,
            {"device_id": _device(hass, current_entry, "STORAGE_pve/local")},
            blocking=True,
        )
    assert _posts(fake_api) == []


async def test_a_node_with_a_run_in_progress_is_skipped_on_request(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """
    Test `skip_if_running` leaves a busy node out and says so.

    vzdump holds one lock per node, so a second run would queue behind the
    first for as long as it takes. Without the flag the call goes through
    and Proxmox queues it, as it always did.
    """
    fake_api.routes[f"nodes/{NODE}/tasks?typefilter=vzdump&source=active&limit=1"] = (
        RUNNING
    )
    await _setup(hass, current_entry)

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_BACKUP,
        {"node": NODE, "all": True, "skip_if_running": True},
        blocking=True,
        return_response=True,
    )
    assert response == {"runs": [], "skipped": [NODE]}
    assert _posts(fake_api) == []

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_BACKUP,
        {"node": NODE, "all": True},
        blocking=True,
        return_response=True,
    )
    assert response["skipped"] == []
    assert len(_posts(fake_api)) == 1
