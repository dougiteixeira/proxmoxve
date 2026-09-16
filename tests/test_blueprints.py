# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for the blueprints shipped in `blueprints/`, loaded the way Home Assistant does."""

import re
from datetime import time
from pathlib import Path

from homeassistant.components.automation.config import async_validate_config_item
from homeassistant.components.blueprint import models
from homeassistant.components.blueprint.schemas import BLUEPRINT_SCHEMA
from homeassistant.core import HomeAssistant
from homeassistant.util import yaml

BLUEPRINTS = Path(__file__).resolve().parent.parent / "blueprints"


def _load(name: str) -> models.Blueprint:
    blueprint = models.Blueprint(
        yaml.load_yaml(str(BLUEPRINTS / name)),
        expected_domain="automation",
        schema=BLUEPRINT_SCHEMA,
    )
    blueprint.validate()
    return blueprint


async def _automation(hass: HomeAssistant, name: str, inputs: dict) -> dict:
    """Fill the blueprint in and validate the result as an automation."""
    filled = models.BlueprintInputs(
        _load(name), {"use_blueprint": {"path": name, "input": inputs}}
    )
    filled.validate()
    # Raises on anything wrong, as it does for the automation editor.
    return await async_validate_config_item(hass, "test", filled.async_substitute())


def test_every_blueprint_is_documented() -> None:
    """Test the readme names each blueprint and links to none that is gone."""
    readme = (BLUEPRINTS / "readme.md").read_text(encoding="utf-8")
    shipped = {p.name for p in BLUEPRINTS.glob("*.yaml")}
    linked = set(re.findall(r"blueprints/([\w-]+\.yaml)", readme))

    assert shipped
    assert linked == shipped


async def test_the_scheduled_backup_fills_in_with_the_targets_alone(
    hass: HomeAssistant,
) -> None:
    """Test picking devices is enough; the rest has defaults."""
    config = await _automation(
        hass, "backup_scheduled.yaml", {"targets": ["device-a", "device-b"]}
    )

    assert config["triggers"][0]["at"] == [time(3, 0)]
    assert config["conditions"][0]["weekday"] == [
        "mon",
        "tue",
        "wed",
        "thu",
        "fri",
        "sat",
        "sun",
    ]
    action = config["actions"][0]
    assert action["action"] == "proxmoxve.backup"
    assert action["target"] == {"device_id": ["device-a", "device-b"]}
    assert action["response_variable"] == "run"


async def test_the_scheduled_backup_posts_what_was_filled_in(
    hass: HomeAssistant,
) -> None:
    """
    Test the action's data is built from the inputs and nothing else.

    Storage, compression and notes are only sent when given, so the
    integration's option and the node's defaults stay in charge otherwise;
    the skip flag always goes along.
    """
    config = await _automation(
        hass,
        "backup_scheduled.yaml",
        {
            "targets": ["device-a"],
            "storage": "nas",
            "mode": "suspend",
            "compress": "zstd",
            "notes": "{{guestname}} from Home Assistant",
        },
    )
    template = config["actions"][0]["data"]
    template.hass = hass
    variables = {
        "storage": "nas",
        "backup_mode": "suspend",
        "compress": "zstd",
        "notes": "{{guestname}} from Home Assistant",
        "skip_if_running": True,
    }

    assert template.async_render(variables) == {
        "mode": "suspend",
        "skip_if_running": True,
        "storage": "nas",
        "compress": "zstd",
        "notes": "{{guestname}} from Home Assistant",
    }

    assert template.async_render(
        {
            **variables,
            "storage": "",
            "compress": "",
            "notes": "",
            "skip_if_running": False,
        }
    ) == {"mode": "suspend", "skip_if_running": False}


async def test_the_notification_says_what_started_and_what_was_skipped(
    hass: HomeAssistant,
) -> None:
    """Test the message reads from the action's response."""
    config = await _automation(
        hass,
        "backup_scheduled.yaml",
        {"targets": ["device-a"], "notify": "notify.phone"},
    )
    template = config["actions"][1]["then"][0]["data"]["message"]
    template.hass = hass

    message = template.async_render(
        {
            "run": {
                "runs": [
                    {
                        "node": "pve",
                        "vmid": "100,101",
                        "storage": "nas",
                        "upid": "UPID:1",
                    },
                    {"node": "pve2", "all": 1, "upid": "UPID:2"},
                ],
                "skipped": ["pve3"],
            }
        }
    )
    assert message == (
        "pve: guests 100,101 to nas (UPID:1); pve2: everything (UPID:2). "
        "Skipped, backup already running: pve3"
    )
    assert (
        template.async_render({"run": {"runs": [], "skipped": []}})
        == "Nothing to back up."
    )
