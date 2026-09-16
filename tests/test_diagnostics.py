# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for what the diagnostics download leaves out."""

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.proxmoxve.const import (
    CONF_HA_ADMIN_PASSWORD,
    CONF_HA_ADMIN_REALM,
    CONF_HA_ADMIN_TOKEN_NAME,
    CONF_HA_ADMIN_USERNAME,
)
from custom_components.proxmoxve.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .fake_api import FakeProxmox

REDACTED = "**REDACTED**"


async def test_every_credential_is_redacted(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """
    Test the optional cluster HA admin credentials never reach the download.

    Only the primary host, user and password were redacted; the HA admin
    password went out in clear text.
    """
    hass.config_entries.async_update_entry(
        current_entry,
        data={
            **current_entry.data,
            CONF_HA_ADMIN_USERNAME: "root",
            CONF_HA_ADMIN_TOKEN_NAME: "",
            CONF_HA_ADMIN_PASSWORD: "admin-secret",
            CONF_HA_ADMIN_REALM: "pam",
        },
    )
    await hass.config_entries.async_setup(current_entry.entry_id)
    await hass.async_block_till_done()

    diagnostics = await async_get_config_entry_diagnostics(hass, current_entry)

    config = diagnostics["config_entry"]
    assert config[CONF_HOST] == REDACTED
    assert config[CONF_USERNAME] == REDACTED
    assert config[CONF_PASSWORD] == REDACTED
    assert config[CONF_HA_ADMIN_USERNAME] == REDACTED
    assert config[CONF_HA_ADMIN_PASSWORD] == REDACTED
    assert "admin-secret" not in str(diagnostics)
    assert "secret" not in str(diagnostics["config_entry"])
