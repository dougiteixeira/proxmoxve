# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for the Proxmox VE API helpers."""

from functools import partial
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from proxmoxer.core import ResourceException

from custom_components.proxmoxve.api import post_api_command
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
