# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for the backup buttons and the storage option behind them."""

from functools import partial
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.proxmoxve import DOMAIN
from custom_components.proxmoxve.api import post_api_command
from custom_components.proxmoxve.const import (
    CONF_BACKUP_STORAGE,
    ProxmoxCommand,
    ProxmoxType,
)
from custom_components.proxmoxve.storage import backup_storage_options

from .fake_api import NODE, FakeProxmox
from .test_setup_full import _setup


def _button_ids(hass: HomeAssistant, entry_id: str) -> set[str]:
    registry = er.async_get(hass)
    return {
        entity.unique_id
        for entity in er.async_entries_for_config_entry(registry, entry_id)
        if entity.domain == "button"
    }


def test_the_dropdown_lists_storages_that_take_backups() -> None:
    """Test only storages with `backup` among their content types are offered, once."""
    listing = [
        {
            "type": "storage",
            "id": "storage/n1/nas",
            "storage": "nas",
            "content": "backup,images",
            "shared": 1,
        },
        {
            "type": "storage",
            "id": "storage/n2/nas",
            "storage": "nas",
            "content": "backup,images",
            "shared": 1,
        },
        {
            "type": "storage",
            "id": "storage/n1/local",
            "storage": "local",
            "content": "vztmpl,backup,iso",
        },
        {
            "type": "storage",
            "id": "storage/n1/local-lvm",
            "storage": "local-lvm",
            "content": "rootdir,images",
        },
        {
            "type": "storage",
            "id": "storage/n1/odd",
            "storage": "odd",
            "content": "backups",
        },
    ]

    assert backup_storage_options(listing) == ["local", "nas"]
    assert backup_storage_options([]) == []


async def test_no_buttons_without_a_storage(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """
    Test the backup buttons are absent until a storage is picked.

    vzdump without a storage dumps into the node's local directory, which
    is never what a button on a dashboard should do without being asked.
    The credentials hold VM.Backup here; the storage is what is missing.
    """
    await _setup(hass, current_entry)
    ids = _button_ids(hass, current_entry.entry_id)
    entry_id = current_entry.entry_id

    assert f"{entry_id}_101_snapshot" in ids
    assert f"{entry_id}_101_backup" not in ids
    assert f"{entry_id}_100_backup" not in ids
    assert f"{entry_id}_{NODE}_backup-all" not in ids


async def test_buttons_appear_with_a_storage_and_the_privilege(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test a picked storage plus VM.Backup gives every guest and node its button."""
    hass.config_entries.async_update_entry(
        current_entry, options={**current_entry.options, CONF_BACKUP_STORAGE: "ext"}
    )
    await _setup(hass, current_entry)
    ids = _button_ids(hass, current_entry.entry_id)
    entry_id = current_entry.entry_id

    assert f"{entry_id}_101_backup" in ids
    assert f"{entry_id}_100_backup" in ids
    assert f"{entry_id}_{NODE}_backup-all" in ids


async def test_no_buttons_without_the_privilege(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test a storage alone is not enough when the credentials lack VM.Backup."""
    fake_api.routes["access/permissions"] = {
        "/": {"Sys.Audit": 1, "VM.Audit": 1, "Datastore.Audit": 1, "VM.Snapshot": 1},
    }
    hass.config_entries.async_update_entry(
        current_entry, options={**current_entry.options, CONF_BACKUP_STORAGE: "ext"}
    )
    await _setup(hass, current_entry)
    ids = _button_ids(hass, current_entry.entry_id)
    entry_id = current_entry.entry_id

    assert f"{entry_id}_101_snapshot" in ids
    assert f"{entry_id}_101_backup" not in ids
    assert f"{entry_id}_{NODE}_backup-all" not in ids


@pytest.mark.parametrize(
    ("command", "api_category", "vm_id", "target"),
    [
        (ProxmoxCommand.BACKUP, ProxmoxType.QEMU, 101, {"vmid": 101}),
        (ProxmoxCommand.BACKUP, ProxmoxType.LXC, 100, {"vmid": 100}),
        (ProxmoxCommand.BACKUP_ALL, ProxmoxType.Node, None, {"all": 1}),
    ],
)
async def test_a_press_posts_one_vzdump_run_to_the_picked_storage(
    hass: HomeAssistant,
    command: ProxmoxCommand,
    api_category: ProxmoxType,
    vm_id: int | None,
    target: dict,
) -> None:
    """Test the button runs vzdump in snapshot mode against the option's storage."""
    proxmox = MagicMock()
    proxmox_client = MagicMock()
    proxmox_client.get_api_client.return_value = proxmox
    entry = MockConfigEntry(
        domain=DOMAIN, data={}, options={CONF_BACKUP_STORAGE: "nas"}
    )
    entity = SimpleNamespace(hass=hass, config_entry=entry)

    await hass.async_add_executor_job(
        partial(
            post_api_command,
            entity,
            proxmox_client=proxmox_client,
            api_category=api_category,
            command=command,
            node="pve",
            vm_id=vm_id,
        )
    )

    proxmox.post.assert_called_once()
    path, kwargs = proxmox.post.call_args.args[0], proxmox.post.call_args.kwargs
    assert path == "nodes/pve/vzdump"
    assert kwargs == {"mode": "snapshot", "storage": "nas", **target}
