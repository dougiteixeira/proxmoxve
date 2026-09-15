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

from custom_components.proxmoxve import DOMAIN

from . import async_init_integration
from .const import MOCK_GET_RESPONSE, USER_INPUT_OK

NO_AUTH_CALL = patch(
    "proxmoxer.backends.https.ProxmoxHTTPAuth._get_new_tokens",
    return_value=None,
)


async def test_unreachable_host_asks_to_be_retried(hass: HomeAssistant) -> None:
    """
    Test a host that is down leaves the entry retrying rather than failed.

    An exception escaping async_setup_entry puts the entry in SETUP_ERROR,
    which Home Assistant never retries - the integration then stays dead until
    someone reloads it by hand, even after Proxmox comes back.
    """
    entry = MockConfigEntry(domain=DOMAIN, title="Test", data=USER_INPUT_OK)

    with (
        patch(
            "proxmoxer.ProxmoxResource.get",
            side_effect=RequestsConnectionError("host is down"),
        ),
        NO_AUTH_CALL,
    ):
        await async_init_integration(hass, entry)

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_reachable_host_sets_up(hass: HomeAssistant) -> None:
    """Test the guard does not get in the way when the host answers."""
    entry = MockConfigEntry(domain=DOMAIN, title="Test", data=USER_INPUT_OK)

    with (
        patch("proxmoxer.ProxmoxResource.get", return_value=MOCK_GET_RESPONSE),
        NO_AUTH_CALL,
    ):
        await async_init_integration(hass, entry)

    assert entry.state is ConfigEntryState.LOADED


async def test_shutdown_stops_the_coordinators(hass: HomeAssistant) -> None:
    """
    Test the stop event stops refreshes from being scheduled.

    Each poll blocks an executor thread until Proxmox answers, and a thread
    cannot be cancelled, so a refresh starting late holds up shutdown.
    """
    entry = MockConfigEntry(domain=DOMAIN, title="Test", data=USER_INPUT_OK)

    with (
        patch("proxmoxer.ProxmoxResource.get", return_value=MOCK_GET_RESPONSE),
        NO_AUTH_CALL,
    ):
        await async_init_integration(hass, entry)

        with patch.object(
            DataUpdateCoordinator, "async_shutdown", new=AsyncMock()
        ) as shutdown:
            hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
            await hass.async_block_till_done()

    assert shutdown.await_count > 0
