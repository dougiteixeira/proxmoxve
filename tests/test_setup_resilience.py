# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for surviving an unreachable Proxmox and a Home Assistant shutdown."""

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from pytest_homeassistant_custom_component.common import MockConfigEntry
from requests.exceptions import ConnectionError as RequestsConnectionError

from .fake_api import FakeProxmox


async def test_unreachable_host_asks_to_be_retried(
    hass: HomeAssistant, current_entry: MockConfigEntry
) -> None:
    """
    Test a host that is down leaves the entry retrying rather than failed.

    An exception escaping async_setup_entry puts the entry in SETUP_ERROR,
    which Home Assistant never retries - the integration then stays dead until
    someone reloads it by hand, even after Proxmox comes back.
    """
    with (
        patch(
            "proxmoxer.ProxmoxResource._request",
            side_effect=RequestsConnectionError("host is down"),
        ),
        patch(
            "proxmoxer.backends.https.ProxmoxHTTPAuth._get_new_tokens",
            return_value=None,
        ),
    ):
        await hass.config_entries.async_setup(current_entry.entry_id)
        await hass.async_block_till_done()

    assert current_entry.state is ConfigEntryState.SETUP_RETRY


async def test_reachable_host_sets_up(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test the guard does not get in the way when the host answers."""
    await hass.config_entries.async_setup(current_entry.entry_id)
    await hass.async_block_till_done()

    assert current_entry.state is ConfigEntryState.LOADED


async def test_shutdown_stops_the_coordinators(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """
    Test the stop event stops refreshes from being scheduled.

    Each poll blocks an executor thread until Proxmox answers, and a thread
    cannot be cancelled, so a refresh starting late holds up shutdown.
    """
    await hass.config_entries.async_setup(current_entry.entry_id)
    await hass.async_block_till_done()

    with patch.object(
        DataUpdateCoordinator, "async_shutdown", new=AsyncMock()
    ) as shutdown:
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
        await hass.async_block_till_done()

    assert shutdown.await_count > 0
