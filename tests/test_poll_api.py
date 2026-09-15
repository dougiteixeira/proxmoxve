# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for how a refused API read turns into a repair issue."""

from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import UpdateFailed
from proxmoxer.core import ResourceException
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.proxmoxve import DOMAIN
from custom_components.proxmoxve.const import ProxmoxType
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
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, f"{entry.entry_id}_{resource_id}_forbiden"
    )
    assert issue is not None
    assert issue.translation_placeholders["resource"] == expected_resource
    assert issue.translation_placeholders["permission"].startswith("['perm'")


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
