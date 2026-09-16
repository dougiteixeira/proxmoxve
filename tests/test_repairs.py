# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for the repairs setup raises and, just as important, clears again."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.proxmoxve import DOMAIN
from custom_components.proxmoxve.const import CONF_QEMU

from .fake_api import FakeProxmox


def _listed(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    """Return the items of the entry's "not found" repair, or "" without one."""
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"{entry.entry_id}_nonexistent")
    return issue.translation_placeholders["items"] if issue else ""


async def _reload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def test_a_picked_guest_the_cluster_does_not_have_raises_a_repair(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test the repair appears for a guest that is picked but not listed."""
    hass.config_entries.async_update_entry(
        current_entry, data={**current_entry.data, CONF_QEMU: ["101", "506"]}
    )

    await hass.config_entries.async_setup(current_entry.entry_id)
    await hass.async_block_till_done()

    listed = _listed(hass, current_entry)
    assert "`QEMU 506`" in listed
    assert "101" not in listed


async def test_removing_the_guest_in_the_options_clears_the_repair(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """
    Test the reported bug: the repair outlived the fix it asked for.

    The repair says "remove it in integration options". Doing exactly that
    reloaded the entry, setup never looked at the guest again, and nothing
    deleted the repair - it stayed until someone ignored it.
    """
    hass.config_entries.async_update_entry(
        current_entry, data={**current_entry.data, CONF_QEMU: ["101", "506"]}
    )
    await hass.config_entries.async_setup(current_entry.entry_id)
    await hass.async_block_till_done()
    assert "`QEMU 506`" in _listed(hass, current_entry)

    hass.config_entries.async_update_entry(
        current_entry, data={**current_entry.data, CONF_QEMU: ["101"]}
    )
    await _reload(hass, current_entry)

    # The last line gone, the repair goes with it.
    assert _listed(hass, current_entry) == ""


async def test_a_repair_for_a_guest_still_tracked_is_left_alone(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test the sweep only touches repairs for resources no longer tracked."""
    hass.config_entries.async_update_entry(
        current_entry, data={**current_entry.data, CONF_QEMU: ["101", "506"]}
    )
    await hass.config_entries.async_setup(current_entry.entry_id)
    await hass.async_block_till_done()

    await _reload(hass, current_entry)

    assert "`QEMU 506`" in _listed(hass, current_entry)


async def test_another_entrys_repairs_are_not_touched(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test the sweep stays inside its own config entry."""
    foreign = "other-entry_nonexistent"
    ir.async_create_issue(
        hass,
        DOMAIN,
        foreign,
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="resources_nonexistent",
        translation_placeholders={},
    )

    await hass.config_entries.async_setup(current_entry.entry_id)
    await hass.async_block_till_done()

    assert ir.async_get(hass).async_get_issue(DOMAIN, foreign)


async def test_two_missing_guests_share_one_repair(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test the repair is one per entry, listing every resource concerned."""
    hass.config_entries.async_update_entry(
        current_entry, data={**current_entry.data, CONF_QEMU: ["101", "506", "507"]}
    )

    await hass.config_entries.async_setup(current_entry.entry_id)
    await hass.async_block_till_done()

    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, f"{current_entry.entry_id}_nonexistent"
    )
    assert issue is not None
    assert issue.translation_placeholders["count"] == "2"
    assert issue.translation_placeholders["items"].splitlines() == [
        "* `QEMU 506` — `['perm','/vms/506',['VM.Audit']]`",
        "* `QEMU 507` — `['perm','/vms/507',['VM.Audit']]`",
    ]
    ours = [
        issue_id
        for domain, issue_id in ir.async_get(hass).issues
        if domain == DOMAIN and issue_id.startswith(current_entry.entry_id)
    ]
    assert ours == [f"{current_entry.entry_id}_nonexistent"]


async def test_the_per_resource_repairs_of_earlier_versions_are_swept_out(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test what an earlier version left in the registry is deleted at setup."""
    registry = ir.async_get(hass)
    for legacy in (
        f"{current_entry.entry_id}_506_resource_nonexistent",
        f"{current_entry.entry_id}_101_forbiden",
    ):
        ir.async_create_issue(
            hass,
            DOMAIN,
            legacy,
            is_fixable=False,
            is_persistent=True,
            severity=ir.IssueSeverity.ERROR,
            translation_key="resources_nonexistent",
            translation_placeholders={},
        )

    await hass.config_entries.async_setup(current_entry.entry_id)
    await hass.async_block_till_done()

    assert not registry.async_get_issue(
        DOMAIN, f"{current_entry.entry_id}_506_resource_nonexistent"
    )
    assert not registry.async_get_issue(
        DOMAIN, f"{current_entry.entry_id}_101_forbiden"
    )
