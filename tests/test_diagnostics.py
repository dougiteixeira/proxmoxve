# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for what the diagnostics download leaves out."""

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME

from custom_components.proxmoxve.const import (
    CONF_HA_ADMIN_PASSWORD,
    CONF_HA_ADMIN_REALM,
    CONF_HA_ADMIN_TOKEN_NAME,
    CONF_HA_ADMIN_USERNAME,
)
from custom_components.proxmoxve.diagnostics import TO_REDACT_CONFIG

from .const import USER_INPUT_OK

REDACTED = "**REDACTED**"


def test_every_credential_is_redacted() -> None:
    """
    Test the optional cluster HA admin credentials never reach the download.

    Only the primary host, user and password were redacted; the HA admin
    password went out in clear text.
    """
    config = async_redact_data(
        {
            **USER_INPUT_OK,
            CONF_HA_ADMIN_USERNAME: "root",
            CONF_HA_ADMIN_TOKEN_NAME: "",
            CONF_HA_ADMIN_PASSWORD: "admin-secret",
            CONF_HA_ADMIN_REALM: "pam",
        },
        TO_REDACT_CONFIG,
    )

    assert config[CONF_HOST] == REDACTED
    assert config[CONF_USERNAME] == REDACTED
    assert config[CONF_PASSWORD] == REDACTED
    assert config[CONF_HA_ADMIN_USERNAME] == REDACTED
    assert config[CONF_HA_ADMIN_PASSWORD] == REDACTED
    assert "secret" not in str(config)
