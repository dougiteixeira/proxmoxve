# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for how a refused API read turns into a repair issue."""

from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import UpdateFailed
from proxmoxer import AuthenticationError
from proxmoxer.core import ResourceException
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.proxmoxve import DOMAIN
from custom_components.proxmoxve.const import PROXMOX_CLIENT, ProxmoxType
from custom_components.proxmoxve.coordinator import poll_api

from .const import USER_INPUT_OK

FORBIDDEN = ResourceException(403, "Forbidden", "Permission check failed")


@pytest.mark.parametrize(
    ("api_path", "api_category", "resource_id", "expected_resource"),
    [
        ("nodes/pve/status", ProxmoxType.Node, "pve", "Node pve"),
        ("nodes/pve/apt/update", ProxmoxType.Update, "Update pve", "Update pve"),
        # The cluster-wide reads pass no resource id at all. This used to
        # raise AttributeError on `None.replace` instead of a repair issue.
        ("cluster/resources", ProxmoxType.Resources, None, "Resources"),
    ],
)
async def test_a_refused_read_raises_a_repair(
    hass: HomeAssistant,
    api_path: str,
    api_category: ProxmoxType,
    resource_id: str | None,
    expected_resource: str,
) -> None:
    """Test a 403 yields None and a repair naming the resource and privilege."""
    entry = MockConfigEntry(domain=DOMAIN, data=USER_INPUT_OK)
    entry.add_to_hass(hass)
    proxmox = MagicMock()
    proxmox.get.side_effect = FORBIDDEN

    result = await hass.async_add_executor_job(
        poll_api, hass, entry, proxmox, api_path, api_category, resource_id
    )

    assert result is None
    await hass.async_block_till_done()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"{entry.entry_id}_forbidden")
    assert issue is not None
    assert issue.translation_placeholders["count"] == "1"
    assert issue.translation_placeholders["items"].startswith(
        f"* `{expected_resource}` — `['perm'"
    )


async def test_other_errors_fail_the_update(hass: HomeAssistant) -> None:
    """Test anything but a 403 is an update failure, not a repair."""
    entry = MockConfigEntry(domain=DOMAIN, data=USER_INPUT_OK)
    entry.add_to_hass(hass)
    proxmox = MagicMock()
    proxmox.get.side_effect = ResourceException(500, "Internal Server Error", "boom")

    with pytest.raises(UpdateFailed):
        await hass.async_add_executor_job(
            poll_api, hass, entry, proxmox, "nodes", ProxmoxType.Node, "pve"
        )


REFUSED = AuthenticationError(
    "Couldn't authenticate user: x@pve to https://h/access/ticket code: 401"
)


def _entry_with_client(
    hass: HomeAssistant, proxmox: MagicMock, *, renews: bool
) -> MockConfigEntry:
    """Return an entry whose stored client built `proxmox` and may log in again."""
    entry = MockConfigEntry(domain=DOMAIN, data=USER_INPUT_OK)
    entry.add_to_hass(hass)
    client = MagicMock()
    client.get_api_client.return_value = proxmox
    client.relogin.return_value = renews
    entry.runtime_data = {PROXMOX_CLIENT: client}
    return entry


async def test_a_refused_ticket_is_renewed_and_the_read_repeated(
    hass: HomeAssistant,
) -> None:
    """
    Test the reported problem: a host off for a night demanded new credentials.

    proxmoxer renews a ticket with the ticket itself. Once that has expired
    the renewal is refused exactly like a wrong password, and the session can
    never recover on its own. A fresh login with the stored password is the
    honest test - and here it works, so the read is simply repeated.
    """
    proxmox = MagicMock()
    proxmox.get.side_effect = [REFUSED, {"status": "online"}]
    entry = _entry_with_client(hass, proxmox, renews=True)

    result = await hass.async_add_executor_job(
        poll_api, hass, entry, proxmox, "nodes/pve/status", ProxmoxType.Node, "pve"
    )

    assert result == {"status": "online"}
    entry.runtime_data[PROXMOX_CLIENT].relogin.assert_called_once()
    assert proxmox.get.call_count == 2


async def test_a_password_that_really_is_wrong_still_asks_for_credentials(
    hass: HomeAssistant,
) -> None:
    """Test the fresh login failing too is what reauthentication is for."""
    proxmox = MagicMock()
    proxmox.get.side_effect = REFUSED
    entry = _entry_with_client(hass, proxmox, renews=True)
    entry.runtime_data[PROXMOX_CLIENT].relogin.side_effect = REFUSED

    with pytest.raises(ConfigEntryAuthFailed):
        await hass.async_add_executor_job(
            poll_api, hass, entry, proxmox, "nodes/pve/status", ProxmoxType.Node, "pve"
        )


async def test_a_token_has_nothing_to_renew(hass: HomeAssistant) -> None:
    """Test token authentication goes straight to reauthentication."""
    proxmox = MagicMock()
    proxmox.get.side_effect = REFUSED
    entry = _entry_with_client(hass, proxmox, renews=False)

    with pytest.raises(ConfigEntryAuthFailed):
        await hass.async_add_executor_job(
            poll_api, hass, entry, proxmox, "nodes/pve/status", ProxmoxType.Node, "pve"
        )
    assert proxmox.get.call_count == 1


async def test_without_a_stored_client_the_failure_stands(hass: HomeAssistant) -> None:
    """Test a poll before setup has stored its client cannot log in again."""
    entry = MockConfigEntry(domain=DOMAIN, data=USER_INPUT_OK)
    entry.add_to_hass(hass)
    proxmox = MagicMock()
    proxmox.get.side_effect = REFUSED

    with pytest.raises(ConfigEntryAuthFailed):
        await hass.async_add_executor_job(
            poll_api, hass, entry, proxmox, "nodes/pve/status", ProxmoxType.Node, "pve"
        )
