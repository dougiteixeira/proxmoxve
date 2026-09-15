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


def _issue_id(entry: MockConfigEntry, resource: str) -> str:
    return f"{entry.entry_id}_{resource}_resource_nonexistent"


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

    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, _issue_id(current_entry, "506"))
    assert not registry.async_get_issue(DOMAIN, _issue_id(current_entry, "101"))


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
    assert ir.async_get(hass).async_get_issue(DOMAIN, _issue_id(current_entry, "506"))

    hass.config_entries.async_update_entry(
        current_entry, data={**current_entry.data, CONF_QEMU: ["101"]}
    )
    await _reload(hass, current_entry)

    assert not ir.async_get(hass).async_get_issue(
        DOMAIN, _issue_id(current_entry, "506")
    )


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

    assert ir.async_get(hass).async_get_issue(DOMAIN, _issue_id(current_entry, "506"))


async def test_another_entrys_repairs_are_not_touched(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test the sweep stays inside its own config entry."""
    foreign = "other-entry_999_resource_nonexistent"
    ir.async_create_issue(
        hass,
        DOMAIN,
        foreign,
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="resource_nonexistent",
        translation_placeholders={},
    )

    await hass.config_entries.async_setup(current_entry.entry_id)
    await hass.async_block_till_done()

    assert ir.async_get(hass).async_get_issue(DOMAIN, foreign)
