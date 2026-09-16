# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for the blueprints shipped in `blueprints/`, loaded the way Home Assistant does."""

import re
from datetime import time
from pathlib import Path

import pytest
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


async def test_the_scheduled_backup_fills_in_with_the_two_required_fields(
    hass: HomeAssistant,
) -> None:
    """Test node and storage are enough; the rest has defaults."""
    config = await _automation(
        hass, "backup_scheduled.yaml", {"node": "pve", "storage": "nas"}
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
    assert config["actions"][0]["action"] == "proxmoxve.backup"
    assert config["actions"][0]["response_variable"] == "run"


async def test_the_scheduled_backup_posts_what_was_filled_in(
    hass: HomeAssistant,
) -> None:
    """
    Test the action's data is built from the inputs and nothing else.

    A guest list turns into `vmid`, an empty one into `all`; compression and
    notes are only sent when given, so the node's defaults stay the node's.
    """
    config = await _automation(
        hass,
        "backup_scheduled.yaml",
        {
            "node": "pve",
            "storage": "nas",
            "vmid": [100, 101],
            "mode": "suspend",
            "compress": "zstd",
            "notes": "{{guestname}} from Home Assistant",
        },
    )
    template = config["actions"][0]["data"]
    template.hass = hass
    variables = {
        "node": "pve",
        "storage": "nas",
        "vmid": [100, 101],
        "backup_mode": "suspend",
        "compress": "zstd",
        "notes": "{{guestname}} from Home Assistant",
    }

    assert template.async_render(variables) == {
        "node": "pve",
        "storage": "nas",
        "mode": "suspend",
        "vmid": [100, 101],
        "compress": "zstd",
        "notes": "{{guestname}} from Home Assistant",
    }

    assert template.async_render(
        {**variables, "vmid": [], "compress": "", "notes": ""}
    ) == {
        "node": "pve",
        "storage": "nas",
        "mode": "suspend",
        "all": True,
    }


@pytest.mark.parametrize(
    ("state", "expected"),
    [("off", True), ("on", False), ("unavailable", True)],
)
async def test_the_scheduled_backup_waits_its_turn(
    hass: HomeAssistant, state: str, *, expected: bool
) -> None:
    """Test a run in progress on the node skips this one; no sensor never does."""
    config = await _automation(
        hass,
        "backup_scheduled.yaml",
        {"node": "pve", "storage": "nas", "backup_running": "binary_sensor.pve_backup"},
    )
    hass.states.async_set("binary_sensor.pve_backup", state)
    template = config["conditions"][1]["value_template"]
    template.hass = hass

    assert (
        template.async_render({"backup_running": "binary_sensor.pve_backup"})
        is expected
    )
    assert template.async_render({"backup_running": ""}) is True
