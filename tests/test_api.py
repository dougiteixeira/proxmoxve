# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for the Proxmox VE API helpers."""

import re
from functools import partial
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from proxmoxer.core import ResourceException

from custom_components.proxmoxve.api import (
    SNAPSHOT_NAME_MAX_LENGTH,
    post_api_command,
    snapshot_name,
)
from custom_components.proxmoxve.const import ProxmoxCommand, ProxmoxType

from .const import mock_config_entry


@pytest.mark.parametrize(
    ("api_category", "expected_path", "expected_kwargs"),
    [
        # LXC config endpoint has no skiplock parameter and rejects it.
        (ProxmoxType.LXC, "nodes/pve/lxc/100/config", {"delete": "lock"}),
        # QEMU needs skiplock=1 to edit a locked guest (root@pam only).
        (
            ProxmoxType.QEMU,
            "nodes/pve/qemu/100/config",
            {"delete": "lock", "skiplock": 1},
        ),
    ],
)
async def test_post_api_command_unlock(
    hass: HomeAssistant,
    api_category: ProxmoxType,
    expected_path: str,
    expected_kwargs: dict,
) -> None:
    """Test unlock sends a PUT to the config endpoint to remove the lock."""
    proxmox = MagicMock()
    proxmox_client = MagicMock()
    proxmox_client.get_api_client.return_value = proxmox

    entity = SimpleNamespace(hass=hass, config_entry=mock_config_entry)

    await hass.async_add_executor_job(
        partial(
            post_api_command,
            entity,
            proxmox_client=proxmox_client,
            api_category=api_category,
            command=ProxmoxCommand.UNLOCK,
            node="pve",
            vm_id=100,
        )
    )

    proxmox.put.assert_called_once_with(expected_path, **expected_kwargs)
    proxmox.post.assert_not_called()


async def test_post_api_command_start_uses_post(hass: HomeAssistant) -> None:
    """Test a regular command uses POST on the status endpoint."""
    proxmox = MagicMock()
    proxmox_client = MagicMock()
    proxmox_client.get_api_client.return_value = proxmox

    entity = SimpleNamespace(hass=hass, config_entry=mock_config_entry)

    await hass.async_add_executor_job(
        partial(
            post_api_command,
            entity,
            proxmox_client=proxmox_client,
            api_category=ProxmoxType.LXC,
            command=ProxmoxCommand.START,
            node="pve",
            vm_id=100,
        )
    )

    proxmox.post.assert_called_once_with("nodes/pve/lxc/100/status/start")
    proxmox.put.assert_not_called()


@pytest.mark.parametrize(
    "command",
    [
        ProxmoxCommand.START_ALL,
        ProxmoxCommand.STOP_ALL,
        ProxmoxCommand.SUSPEND_ALL,
        ProxmoxCommand.WAKEONLAN,
    ],
)
async def test_post_api_command_node_bulk_actions(
    hass: HomeAssistant, command: ProxmoxCommand
) -> None:
    """Test the bulk node actions post to their own endpoint, not status."""
    proxmox = MagicMock()
    proxmox_client = MagicMock()
    proxmox_client.get_api_client.return_value = proxmox

    entity = SimpleNamespace(hass=hass, config_entry=mock_config_entry)

    await hass.async_add_executor_job(
        partial(
            post_api_command,
            entity,
            proxmox_client=proxmox_client,
            api_category=ProxmoxType.Node,
            command=command,
            node="pve",
        )
    )

    proxmox.post.assert_called_once_with(f"nodes/pve/{command}")


def test_snapshot_name_is_one_the_api_accepts() -> None:
    """Test the generated name fits Proxmox's `pve-configid` rules."""
    name = snapshot_name()

    assert re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]+", name)
    assert len(name) <= SNAPSHOT_NAME_MAX_LENGTH
    assert name.startswith("homeassistant_")


@pytest.mark.parametrize("api_category", [ProxmoxType.QEMU, ProxmoxType.LXC])
async def test_post_api_command_snapshot(
    hass: HomeAssistant, api_category: ProxmoxType
) -> None:
    """Test a snapshot posts to the snapshot endpoint with a name."""
    proxmox = MagicMock()
    proxmox_client = MagicMock()
    proxmox_client.get_api_client.return_value = proxmox

    entity = SimpleNamespace(hass=hass, config_entry=mock_config_entry)

    await hass.async_add_executor_job(
        partial(
            post_api_command,
            entity,
            proxmox_client=proxmox_client,
            api_category=api_category,
            command=ProxmoxCommand.SNAPSHOT,
            node="pve",
            vm_id=100,
        )
    )

    proxmox.post.assert_called_once()
    path, kwargs = proxmox.post.call_args.args[0], proxmox.post.call_args.kwargs
    assert path == f"nodes/pve/{api_category}/100/snapshot"
    assert kwargs["snapname"].startswith("homeassistant_")
    assert kwargs["description"] == "Created by Home Assistant"
    # Disks only: no RAM state, which would make the snapshot slow and big.
    assert "vmstate" not in kwargs


async def test_post_api_command_surfaces_non_403_error(hass: HomeAssistant) -> None:
    """Test a non-403 API error is raised instead of being swallowed."""
    proxmox = MagicMock()
    proxmox.put.side_effect = ResourceException(
        500, "Internal Server Error", "CT is locked (fstrim)"
    )
    proxmox_client = MagicMock()
    proxmox_client.get_api_client.return_value = proxmox

    entity = SimpleNamespace(hass=hass, config_entry=mock_config_entry)

    with pytest.raises(HomeAssistantError):
        await hass.async_add_executor_job(
            partial(
                post_api_command,
                entity,
                proxmox_client=proxmox_client,
                api_category=ProxmoxType.LXC,
                command=ProxmoxCommand.UNLOCK,
                node="pve",
                vm_id=100,
            )
        )
