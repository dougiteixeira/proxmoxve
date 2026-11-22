# ruff: noqa: CPY001
"""Migrate registry entries from the legacy integration domain."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import entity_sources

from .const import DOMAIN, DOMAIN_OLD, LEGACY_ENTRY_VERSION, LOGGER

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


def _remove_legacy_component(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        return
    try:
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        if (
            not isinstance(manifest, dict)
            or manifest.get("domain") != DOMAIN_OLD
            or manifest.get("name") != "Proxmox VE Custom"
            or manifest.get("documentation")
            != "https://github.com/dougiteixeira/proxmoxve"
        ):
            return
        shutil.rmtree(path)
    except (OSError, ValueError, TypeError) as error:
        LOGGER.warning(
            "Could not remove legacy integration directory %s: %s", path, error
        )


async def async_cleanup_legacy_component(hass: HomeAssistant) -> None:
    """Remove the installed legacy component when no migrations remain."""
    if hass.config_entries.async_entries(DOMAIN_OLD):
        return
    if any(
        entry.data.get("_legacy_entry_id")
        for entry in hass.config_entries.async_entries(DOMAIN)
    ):
        return
    path = Path(hass.config.path("custom_components", DOMAIN_OLD))
    await hass.async_add_executor_job(_remove_legacy_component, path)


async def async_migrate_registry(
    hass: HomeAssistant, old_entry: ConfigEntry, new_entry: ConfigEntry
) -> None:
    """Transfer unloaded entities and devices to the replacement entry."""
    if old_entry.domain != DOMAIN_OLD or old_entry.version != LEGACY_ENTRY_VERSION:
        message = "Only legacy version 7 entries can be migrated"
        raise HomeAssistantError(message)
    entities = er.async_get(hass)
    old_entities = er.async_entries_for_config_entry(entities, old_entry.entry_id)
    loaded_entities = entity_sources(hass)
    for entity in old_entities:
        if entity.entity_id in loaded_entities:
            message = f"Entity is still loaded: {entity.entity_id}"
            raise HomeAssistantError(message)
        unique_id = entity.unique_id
        if unique_id.startswith(f"{old_entry.entry_id}_"):
            unique_id = new_entry.entry_id + unique_id[len(old_entry.entry_id) :]
        existing = entities.async_get_entity_id(entity.domain, DOMAIN, unique_id)
        if existing is not None and existing != entity.entity_id:
            message = f"Entity migration conflict: {existing}"
            raise HomeAssistantError(message)

    devices = dr.async_get(hass)
    old_devices = dr.async_entries_for_config_entry(devices, old_entry.entry_id)
    for device in old_devices:
        for domain, identifier in device.identifiers:
            if domain != DOMAIN_OLD:
                continue
            new_identifier = identifier
            if identifier.startswith(f"{old_entry.entry_id}_"):
                new_identifier = (
                    new_entry.entry_id + identifier[len(old_entry.entry_id) :]
                )
            existing_device = devices.async_get_device(
                identifiers={(DOMAIN, new_identifier)}
            )
            if existing_device is not None and existing_device.id != device.id:
                message = f"Device migration conflict: {existing_device.id}"
                raise HomeAssistantError(message)

    for entity in old_entities:
        unique_id = entity.unique_id
        if unique_id.startswith(f"{old_entry.entry_id}_"):
            unique_id = new_entry.entry_id + unique_id[len(old_entry.entry_id) :]
        entities.async_update_entity_platform(
            entity.entity_id,
            DOMAIN,
            new_config_entry_id=new_entry.entry_id,
            new_unique_id=unique_id,
        )

    for device in old_devices:
        identifiers = {
            (
                DOMAIN,
                new_entry.entry_id + identifier[len(old_entry.entry_id) :]
                if identifier.startswith(f"{old_entry.entry_id}_")
                else identifier,
            )
            if domain == DOMAIN_OLD
            else (domain, identifier)
            for domain, identifier in device.identifiers
        }
        devices.async_update_device(
            device.id,
            new_identifiers=identifiers,
            new_config_entry_id=new_entry.entry_id,
        )
