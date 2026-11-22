# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for migrating config entries from earlier versions."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryDisabler, ConfigEntryState
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.loader import IntegrationNotFound
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.proxmoxve_custom.const import (
    CONF_LXC,
    CONF_NODE,
    CONF_NODES,
    CONF_QEMU,
    CONF_REALM,
    CONF_STORAGE,
    CONF_TOKEN_NAME,
)
from custom_components.proxmoxve_custom.migration import (
    async_cleanup_legacy_component,
    async_migrate_registry,
)

from .const import CURRENT_ENTRY_DATA, CURRENT_ENTRY_VERSION
from .fake_api import FakeProxmox

# What the very first config flow stored: one node under a singular key.
VERSION_1_DATA = {
    CONF_HOST: "192.168.10.101",
    CONF_PORT: 8006,
    CONF_USERNAME: "root",
    CONF_TOKEN_NAME: "",
    CONF_PASSWORD: "secret",
    CONF_REALM: "pam",
    CONF_VERIFY_SSL: True,
    CONF_NODE: "pve",
    CONF_QEMU: ["101"],
    CONF_LXC: ["100"],
}

CORE_ENTRY_DATA = {
    CONF_HOST: "192.168.10.101",
    CONF_PORT: 8006,
    CONF_USERNAME: "root",
    CONF_PASSWORD: "secret",
    CONF_REALM: "pam",
    CONF_VERIFY_SSL: True,
    "auth_method": "pam",
    "nodes": [{"node": "pve", "vms": [101], "containers": [100]}],
}


@pytest.fixture
def legacy_path(
    hass: HomeAssistant, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Point legacy cleanup at a directory unique to this test."""
    legacy = tmp_path / "custom_components" / "proxmoxve"
    original_path = hass.config.path

    def config_path(*path: str) -> str:
        if path == ("custom_components", "proxmoxve"):
            return str(legacy)
        return original_path(*path)

    monkeypatch.setattr(hass.config, "path", config_path)
    return legacy


def _legacy_directory(legacy: Path) -> Path:
    """Create a legacy installation under the test configuration directory."""
    legacy.mkdir(parents=True)
    (legacy / "manifest.json").write_text(
        json.dumps(
            {
                "domain": "proxmoxve",
                "name": "Proxmox VE Custom",
                "documentation": "https://github.com/dougiteixeira/proxmoxve",
            }
        ),
        encoding="utf-8",
    )
    return legacy


def test_hacs_uses_the_new_component_release() -> None:
    """HACS must identify and download the new domain rather than the legacy one."""
    root = Path(__file__).resolve().parent.parent
    hacs = json.loads((root / "hacs.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    component_manifest = json.loads(
        (root / "custom_components/proxmoxve_custom/manifest.json").read_text(
            encoding="utf-8"
        )
    )

    assert hacs["content_in_root"] is True
    assert hacs["hide_default_branch"] is True
    assert hacs["filename"] == "proxmoxve_custom.zip"
    assert hacs["zip_release"] is True
    assert manifest == component_manifest


@pytest.mark.parametrize("language", ["en", "pt", "pt-BR"])
def test_legacy_upgrade_repair_has_translations(language: str) -> None:
    """The legacy upgrade repair names the required integration release."""
    root = Path(__file__).resolve().parent.parent
    path = (
        root / "custom_components" / "proxmoxve" / "translations" / f"{language}.json"
    )
    issue = json.loads(path.read_text(encoding="utf-8"))["issues"][
        "legacy_upgrade_required"
    ]
    assert "5.3.5" in issue["description"]
    assert "{version}" in issue["description"]
    assert "{host}" in issue["title"]


async def test_removes_legacy_directory_when_no_entries_remain(
    hass: HomeAssistant, legacy_path: Path
) -> None:
    """Delete the installed legacy component after all entries have moved."""
    legacy = _legacy_directory(legacy_path)

    await async_cleanup_legacy_component(hass)

    assert not legacy.exists()


@pytest.mark.parametrize("pending", ["enabled", "disabled", "migration"])
async def test_keeps_legacy_directory_while_entries_remain(
    hass: HomeAssistant, legacy_path: Path, pending: str
) -> None:
    """Keep the old component for active, disabled and incomplete entries."""
    legacy = _legacy_directory(legacy_path)
    if pending == "migration":
        entry = MockConfigEntry(
            domain="proxmoxve_custom", data={"_legacy_entry_id": "old"}, version=1
        )
    else:
        entry = MockConfigEntry(
            domain="proxmoxve",
            data={},
            version=7,
            disabled_by=ConfigEntryDisabler.USER if pending == "disabled" else None,
        )
    entry.add_to_hass(hass)

    await async_cleanup_legacy_component(hass)

    assert legacy.exists()


async def test_does_not_remove_unrecognized_legacy_component(
    hass: HomeAssistant, legacy_path: Path
) -> None:
    """Never delete another integration that happens to use the old domain."""
    legacy = _legacy_directory(legacy_path)
    (legacy / "manifest.json").write_text('{"domain": "proxmoxve"}', encoding="utf-8")

    await async_cleanup_legacy_component(hass)

    assert legacy.exists()


async def test_does_not_remove_legacy_symlink(
    hass: HomeAssistant, legacy_path: Path, tmp_path: Path
) -> None:
    """Keep symlinked installations and their targets untouched."""
    legacy = legacy_path
    legacy.parent.mkdir(parents=True, exist_ok=True)
    target = tmp_path / "legacy_target"
    target.mkdir()
    legacy.symlink_to(target, target_is_directory=True)

    await async_cleanup_legacy_component(hass)

    assert legacy.is_symlink()
    assert target.exists()


async def test_cleanup_logs_a_filesystem_error(
    hass: HomeAssistant, legacy_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Keep the integration running if the legacy directory cannot be removed."""
    legacy = _legacy_directory(legacy_path)
    with patch(
        "custom_components.proxmoxve_custom.migration.shutil.rmtree",
        side_effect=PermissionError("read-only directory"),
    ):
        await async_cleanup_legacy_component(hass)

    assert legacy.exists()
    assert "Could not remove legacy integration directory" in caplog.text


async def test_cleanup_retries_on_new_component_startup(
    hass: HomeAssistant,
    fake_api: FakeProxmox,
    current_entry: MockConfigEntry,
    legacy_path: Path,
) -> None:
    """Remove a recognized legacy directory recreated by a later update."""
    legacy = _legacy_directory(legacy_path)

    await hass.config_entries.async_setup(current_entry.entry_id)
    await hass.async_block_till_done()

    assert current_entry.state is ConfigEntryState.LOADED
    assert not legacy.exists()


async def test_keeps_legacy_directory_if_new_setup_fails(
    hass: HomeAssistant,
    fake_api: FakeProxmox,
    current_entry: MockConfigEntry,
    legacy_path: Path,
) -> None:
    """Do not remove the legacy installation when new setup fails."""
    legacy = _legacy_directory(legacy_path)
    with patch(
        "custom_components.proxmoxve_custom.ProxmoxClient.build_client",
        side_effect=ConnectionError("offline"),
    ):
        await hass.config_entries.async_setup(current_entry.entry_id)
        await hass.async_block_till_done()

    assert current_entry.state is not ConfigEntryState.LOADED
    assert legacy.exists()


async def test_a_version_1_entry_keeps_its_resources_without_migration(
    hass: HomeAssistant, fake_api: FakeProxmox
) -> None:
    """Keep the old entry while loading its node and guest selection."""
    entry = MockConfigEntry(
        domain="proxmoxve", title="Test", data=VERSION_1_DATA, version=1
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.proxmoxve.async_get_integration",
        side_effect=IntegrationNotFound("proxmoxve_custom"),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.version == 1
    assert entry.runtime_data["tracked"][CONF_NODES] == ["pve"]
    assert entry.runtime_data["tracked"][CONF_QEMU] == ["101"]
    assert entry.runtime_data["tracked"][CONF_LXC] == ["100"]
    assert entry.runtime_data["tracked"][CONF_STORAGE] == []
    assert entry.data[CONF_HOST] == "192.168.10.101"


async def test_legacy_fallback_preserves_options(
    hass: HomeAssistant, fake_api: FakeProxmox
) -> None:
    """Do not reset options while the entry waits for an upgrade."""
    entry = MockConfigEntry(
        domain="proxmoxve",
        title="Test",
        data=VERSION_1_DATA,
        options={"disks_enable": False},
        version=1,
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.proxmoxve.async_get_integration",
        side_effect=IntegrationNotFound("proxmoxve_custom"),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.options == {"disks_enable": False}


async def test_version_1_legacy_options_can_show_resource_selection(
    hass: HomeAssistant, fake_api: FakeProxmox
) -> None:
    """The original entry format can still open the resource selection."""
    entry = MockConfigEntry(domain="proxmoxve", data=VERSION_1_DATA, version=1)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "change_expose"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "change_expose"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_NODES: ["pve"],
            CONF_QEMU: ["101"],
            CONF_LXC: ["100"],
            CONF_STORAGE: [],
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "changes_successful"
    assert entry.version == 1
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data["tracked"][CONF_NODES] == ["pve"]


async def test_domain_migration_preserves_registry_ids(hass: HomeAssistant) -> None:
    """Move an unloaded entry's devices and entities to the new domain."""
    old_entry = MockConfigEntry(domain="proxmoxve", data=CURRENT_ENTRY_DATA, version=7)
    new_entry = MockConfigEntry(domain="proxmoxve_custom", data={}, version=1)
    old_entry.add_to_hass(hass)
    new_entry.add_to_hass(hass)
    devices = dr.async_get(hass)
    device = devices.async_get_or_create(
        config_entry_id=old_entry.entry_id,
        identifiers={("proxmoxve", f"{old_entry.entry_id}_NODE_pve")},
        name="Node",
    )
    entities = er.async_get(hass)
    entity = entities.async_get_or_create(
        "sensor",
        "proxmoxve",
        f"{old_entry.entry_id}_pve_cpu",
        config_entry=old_entry,
        device_id=device.id,
        suggested_object_id="pve_cpu",
    )

    await async_migrate_registry(hass, old_entry, new_entry)

    migrated = entities.async_get(entity.entity_id)
    assert migrated is not None
    assert migrated.platform == "proxmoxve_custom"
    assert migrated.config_entry_id == new_entry.entry_id
    assert migrated.unique_id == f"{new_entry.entry_id}_pve_cpu"
    assert migrated.device_id == device.id
    updated_device = devices.async_get(device.id)
    assert updated_device is not None
    assert ("proxmoxve_custom", f"{new_entry.entry_id}_NODE_pve") in (
        updated_device.identifiers
    )
    assert updated_device.config_entry_id == new_entry.entry_id
    await async_migrate_registry(hass, old_entry, new_entry)
    assert entities.async_get(entity.entity_id) == migrated


@pytest.mark.parametrize("version", [1, 6, 8])
async def test_migration_flow_rejects_other_legacy_versions(
    hass: HomeAssistant, version: int
) -> None:
    """Only a legacy version 7 entry can create a replacement."""
    old_entry = MockConfigEntry(
        domain="proxmoxve", data=CURRENT_ENTRY_DATA, version=version
    )
    old_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        "proxmoxve_custom",
        context={"source": "proxmoxve_migration"},
        data={"entry_id": old_entry.entry_id},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert hass.config_entries.async_get_entry(old_entry.entry_id) is old_entry
    assert not hass.config_entries.async_entries("proxmoxve_custom")


@pytest.mark.parametrize("version", [1, 6, 8])
async def test_registry_migration_rejects_other_legacy_versions(
    hass: HomeAssistant, version: int
) -> None:
    """Registry migration cannot bypass the legacy version check."""
    old_entry = MockConfigEntry(
        domain="proxmoxve", data=CURRENT_ENTRY_DATA, version=version
    )
    new_entry = MockConfigEntry(domain="proxmoxve_custom", data={}, version=1)
    old_entry.add_to_hass(hass)
    new_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    entity = registry.async_get_or_create(
        "sensor", "proxmoxve", f"{old_entry.entry_id}_cpu", config_entry=old_entry
    )

    with pytest.raises(HomeAssistantError):
        await async_migrate_registry(hass, old_entry, new_entry)

    assert registry.async_get(entity.entity_id) == entity


async def test_domain_migration_rejects_entity_collisions(hass: HomeAssistant) -> None:
    """Leave the legacy registries untouched when a unique ID is already in use."""
    old_entry = MockConfigEntry(domain="proxmoxve", data=CURRENT_ENTRY_DATA, version=7)
    new_entry = MockConfigEntry(domain="proxmoxve_custom", data={}, version=1)
    old_entry.add_to_hass(hass)
    new_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    original = registry.async_get_or_create(
        "sensor", "proxmoxve", f"{old_entry.entry_id}_pve_cpu", config_entry=old_entry
    )
    registry.async_get_or_create(
        "sensor",
        "proxmoxve_custom",
        f"{new_entry.entry_id}_pve_cpu",
        config_entry=new_entry,
    )

    with pytest.raises(HomeAssistantError):
        await async_migrate_registry(hass, old_entry, new_entry)

    assert registry.async_get(original.entity_id) == original


async def test_domain_migration_rejects_loaded_entities_before_moving_anything(
    hass: HomeAssistant,
) -> None:
    """A loaded entity must not leave the entry only partly migrated."""
    old_entry = MockConfigEntry(domain="proxmoxve", data=CURRENT_ENTRY_DATA, version=7)
    new_entry = MockConfigEntry(domain="proxmoxve_custom", data={}, version=1)
    old_entry.add_to_hass(hass)
    new_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    first = registry.async_get_or_create(
        "sensor", "proxmoxve", f"{old_entry.entry_id}_first", config_entry=old_entry
    )
    second = registry.async_get_or_create(
        "sensor", "proxmoxve", f"{old_entry.entry_id}_second", config_entry=old_entry
    )
    with (
        patch(
            "custom_components.proxmoxve_custom.migration.entity_sources",
            return_value={second.entity_id: {}},
        ),
        pytest.raises(HomeAssistantError),
    ):
        await async_migrate_registry(hass, old_entry, new_entry)

    assert registry.async_get(first.entity_id) == first
    assert registry.async_get(second.entity_id) == second


async def test_legacy_entry_is_replaced_automatically(
    hass: HomeAssistant, fake_api: FakeProxmox, legacy_path: Path
) -> None:
    """Set up a legacy entry and migrate its registries and settings."""
    legacy = _legacy_directory(legacy_path)
    old_entry = MockConfigEntry(
        domain="proxmoxve",
        title="Original",
        data=CURRENT_ENTRY_DATA,
        options={"disks_enable": False},
        unique_id="legacy-cluster",
        pref_disable_polling=True,
        version=7,
    )
    old_entry.add_to_hass(hass)
    devices = dr.async_get(hass)
    device = devices.async_get_or_create(
        config_entry_id=old_entry.entry_id,
        identifiers={("proxmoxve", f"{old_entry.entry_id}_NODE_pve")},
    )
    entities = er.async_get(hass)
    entity = entities.async_get_or_create(
        "sensor",
        "proxmoxve",
        f"{old_entry.entry_id}_pve_cpu",
        config_entry=old_entry,
        device_id=device.id,
        suggested_object_id="original_pve_cpu",
    )
    hass.config_entries.async_update_entry(old_entry, pref_disable_new_entities=True)

    await hass.config_entries.async_setup(old_entry.entry_id)
    await hass.async_block_till_done()

    entries = hass.config_entries.async_entries("proxmoxve_custom")
    assert len(entries) == 1
    new_entry = entries[0]
    assert new_entry.version == CURRENT_ENTRY_VERSION == 1
    assert all(new_entry.data[key] == value for key, value in old_entry.data.items())
    assert new_entry.options == old_entry.options
    assert new_entry.unique_id == old_entry.unique_id
    assert new_entry.pref_disable_new_entities
    assert new_entry.pref_disable_polling
    assert hass.config_entries.async_get_entry(old_entry.entry_id) is None
    migrated = entities.async_get(entity.entity_id)
    assert migrated is not None
    assert migrated.config_entry_id == new_entry.entry_id
    assert migrated.device_id == device.id
    assert hass.states.get(entity.entity_id) is not None
    assert hass.services.has_service("proxmoxve", "backup")
    assert hass.services.has_service("proxmoxve_custom", "backup")
    assert not legacy.exists()
    issue = ir.async_get(hass).async_get_issue(
        "proxmoxve_custom", "domain_migration_restart"
    )
    assert issue is not None
    assert issue.is_fixable
    assert not issue.is_persistent


async def test_legacy_entry_stays_available_without_new_component(
    hass: HomeAssistant, fake_api: FakeProxmox
) -> None:
    """Keep the old integration working when the new component is missing."""
    entry = MockConfigEntry(domain="proxmoxve", data=CURRENT_ENTRY_DATA, version=7)
    entry.add_to_hass(hass)
    with patch(
        "custom_components.proxmoxve.async_get_integration",
        side_effect=IntegrationNotFound("proxmoxve_custom"),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert hass.config_entries.async_get_entry(entry.entry_id) is entry
    assert hass.services.has_service("proxmoxve", "backup")
    assert not hass.config_entries.async_entries("proxmoxve_custom")


async def test_core_entry_is_not_migrated(hass: HomeAssistant) -> None:
    """Do not mutate an entry belonging to the native integration."""
    entry = MockConfigEntry(
        domain="proxmoxve", data={"host": "pve", "nodes": []}, version=3
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.config_entries.async_get_entry(entry.entry_id) is entry
    assert entry.version == 3
    assert dict(entry.data) == {"host": "pve", "nodes": []}
    assert not hass.config_entries.async_entries("proxmoxve_custom")


@pytest.mark.parametrize("version", [3, 7])
async def test_core_entry_cannot_start_domain_migration(
    hass: HomeAssistant, fake_api: FakeProxmox, version: int
) -> None:
    """Reject the native format even when its version matches the custom one."""
    entry = MockConfigEntry(domain="proxmoxve", data=CORE_ENTRY_DATA, version=version)
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        "proxmoxve_custom",
        context={"source": "proxmoxve_migration"},
        data={"entry_id": entry.entry_id},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert hass.config_entries.async_get_entry(entry.entry_id) is entry
    assert not hass.config_entries.async_entries("proxmoxve_custom")


@pytest.mark.parametrize("version", [3, 7])
async def test_core_entry_registry_cannot_be_migrated(
    hass: HomeAssistant, version: int
) -> None:
    """Protect a native entry's entities when registry migration is called directly."""
    old_entry = MockConfigEntry(
        domain="proxmoxve", data=CORE_ENTRY_DATA, version=version
    )
    new_entry = MockConfigEntry(domain="proxmoxve_custom", data={}, version=1)
    old_entry.add_to_hass(hass)
    new_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    entity = registry.async_get_or_create(
        "sensor", "proxmoxve", "core-cpu", config_entry=old_entry
    )

    with pytest.raises(HomeAssistantError):
        await async_migrate_registry(hass, old_entry, new_entry)

    assert registry.async_get(entity.entity_id) == entity


async def test_core_entry_is_not_removed_by_pending_migration(
    hass: HomeAssistant,
) -> None:
    """An invalid pending migration must not delete or transfer a native entry."""
    old_entry = MockConfigEntry(
        domain="proxmoxve",
        data=CORE_ENTRY_DATA,
        version=7,
        pref_disable_new_entities=True,
    )
    new_entry = MockConfigEntry(
        domain="proxmoxve_custom",
        data={**CORE_ENTRY_DATA, "_legacy_entry_id": old_entry.entry_id},
        version=1,
    )
    old_entry.add_to_hass(hass)
    new_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    entity = registry.async_get_or_create(
        "sensor", "proxmoxve", "core-cpu", config_entry=old_entry
    )

    await hass.config_entries.async_setup(new_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.config_entries.async_get_entry(old_entry.entry_id) is old_entry
    assert registry.async_get(entity.entity_id) == entity
    assert new_entry.data["_legacy_entry_id"] == old_entry.entry_id
    assert not new_entry.pref_disable_new_entities


@pytest.mark.parametrize("version", [1, 2, 3, 4, 5, 6])
@pytest.mark.parametrize("new_component_installed", [True, False])
async def test_old_legacy_version_loads_and_requests_upgrade(
    hass: HomeAssistant,
    fake_api: FakeProxmox,
    version: int,
    *,
    new_component_installed: bool,
) -> None:
    """Load legacy entries without domain migration and request version 5.3.5."""
    data = VERSION_1_DATA if version == 1 else CURRENT_ENTRY_DATA
    entry = MockConfigEntry(domain="proxmoxve", data=data, version=version)
    entry.add_to_hass(hass)
    registry = dr.async_get(hass)
    device = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("proxmoxve", "192.168.10.101_8006_pve")},
    )

    with patch(
        "custom_components.proxmoxve.async_get_integration",
        side_effect=None
        if new_component_installed
        else IntegrationNotFound("proxmoxve_custom"),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.version == version
    assert entry.runtime_data["tracked"][CONF_NODES] == ["pve"]
    assert registry.async_get(device.id) is not None
    assert not hass.config_entries.async_entries("proxmoxve_custom")
    issue = ir.async_get(hass).async_get_issue(
        "proxmoxve", f"{entry.entry_id}_legacy_upgrade_required"
    )
    assert issue is not None
    assert issue.translation_key == "legacy_upgrade_required"
    assert issue.translation_placeholders == {
        "host": "192.168.10.101",
        "version": str(version),
    }
    assert not issue.is_fixable
