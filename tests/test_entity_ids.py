# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""
Tests for the optional entity id scheme.

Upstream #573 asked for a common prefix so the recorder and a search can
catch everything of the integration; #604 asked for the id before the
name so a list sorts by it. Both as the `extended` scheme, a choice that
changes nothing for entities that already have an id.
"""

import re

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.proxmoxve import DOMAIN
from custom_components.proxmoxve.const import (
    CONF_ENTITY_ID_PREFIX,
    CONF_ENTITY_ID_SCHEME,
    SCHEME_EXTENDED,
)
from custom_components.proxmoxve.entity import scheme_object_id

from .fake_api import NODE, FakeProxmox
from .test_setup_full import _setup


@pytest.mark.parametrize(
    ("identifier", "device_name", "item", "guest_name", "expected"),
    [
        (
            "cluster",
            "Proxmox Cluster",
            "nodes_online",
            None,
            "pve_cluster_nodes_online",
        ),
        ("NODE_pve", "Node pve", "cpu_used", None, "pve_node_pve_cpu_used"),
        (
            "QEMU_108",
            "QEMU win11 (108)",
            "cpu_used",
            "win11",
            "pve_qemu_108_win11_cpu_used",
        ),
        (
            "QEMU_108",
            "QEMU win11 (108)",
            "cpu_used",
            None,
            "pve_qemu_108_win11_cpu_used",
        ),
        (
            "LXC_109",
            "LXC docmost (109)",
            "status",
            "docmost",
            "pve_lxc_109_docmost_status",
        ),
        (
            "STORAGE_pve/local",
            "Storage local",
            "disk_used",
            None,
            "pve_storage_pve_local_disk_used",
        ),
        ("STORAGE_nas", "Storage nas", "disk_used", None, "pve_storage_nas_disk_used"),
        (
            "DISK_pve_ata-Samsung_SSD",
            "Disk pve: Samsung SSD 870",
            "temperature",
            None,
            "pve_disk_pve_samsung_ssd_870_temperature",
        ),
        (
            "ZFS_pve_rpool",
            "ZFS pve: rpool",
            "free_perc",
            None,
            "pve_zfs_pve_rpool_free_perc",
        ),
    ],
)
def test_the_scheme_from_the_device_identifier(
    identifier: str, device_name: str, item: str, guest_name: str | None, expected: str
) -> None:
    """Test each kind of device yields prefix, kind, id, name, item - in that order."""
    assert (
        scheme_object_id("pve", identifier, device_name, item, guest_name) == expected
    )


def test_the_prefix_is_whatever_was_typed() -> None:
    """Test the prefix is slugified along with the rest."""
    assert (
        scheme_object_id("My Lab", "NODE_pve", "Node pve", "cpu_used")
        == "my_lab_node_pve_cpu_used"
    )


def _entity_id(
    hass: HomeAssistant, entry: MockConfigEntry, domain: str, suffix: str
) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, f"{entry.entry_id}_{suffix}"
    )
    assert entity_id is not None, suffix
    return entity_id


async def test_the_standard_scheme_is_home_assistants(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test an entry without the option - every existing one - keeps HA's ids."""
    await _setup(hass, current_entry)

    assert (
        _entity_id(hass, current_entry, "sensor", f"{NODE}_cpu")
        == "sensor.node_pve_cpu_used"
    )
    assert _entity_id(hass, current_entry, "sensor", "101_status_raw").startswith(
        "sensor.qemu_vm_test_101_101_"
    )


async def test_the_extended_scheme_covers_every_kind_of_entity(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test node, guest, storage, disk, pool and cluster entities, and the update entity."""
    hass.config_entries.async_update_entry(
        current_entry,
        options={**current_entry.options, CONF_ENTITY_ID_SCHEME: SCHEME_EXTENDED},
    )
    await _setup(hass, current_entry)

    assert (
        _entity_id(hass, current_entry, "sensor", f"{NODE}_cpu")
        == "sensor.pve_node_pve_cpu_used"
    )
    assert (
        _entity_id(hass, current_entry, "sensor", "101_status_raw")
        == "sensor.pve_qemu_101_vm_test_101_status_raw"
    )
    assert (
        _entity_id(hass, current_entry, "sensor", "100_status_raw")
        == "sensor.pve_lxc_100_lxc_test_100_status_raw"
    )
    assert (
        _entity_id(hass, current_entry, "binary_sensor", "storage/pve/local_active")
        == "binary_sensor.pve_storage_pve_local_storage_active"
    )
    assert (
        _entity_id(hass, current_entry, "update", "pve_node_update")
        == "update.pve_node_pve_node_update"
    )
    registry = er.async_get(hass)
    ours = [
        entity.entity_id
        for entity in er.async_entries_for_config_entry(
            registry, current_entry.entry_id
        )
    ]
    assert ours
    assert all(
        re.match(r"^\w+\.pve_(cluster|node|qemu|lxc|storage|disk|zfs)_", e)
        for e in ours
    ), [
        e
        for e in ours
        if not re.match(r"^\w+\.pve_(cluster|node|qemu|lxc|storage|disk|zfs)_", e)
    ]


async def test_the_prefix_option_is_used(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test a prefix of one's own replaces `pve`."""
    hass.config_entries.async_update_entry(
        current_entry,
        options={
            **current_entry.options,
            CONF_ENTITY_ID_SCHEME: SCHEME_EXTENDED,
            CONF_ENTITY_ID_PREFIX: "hv",
        },
    )
    await _setup(hass, current_entry)

    assert (
        _entity_id(hass, current_entry, "sensor", f"{NODE}_cpu")
        == "sensor.hv_node_pve_cpu_used"
    )


async def test_switching_to_extended_later_leaves_existing_ids_alone(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """
    Test the promise made in the option's description.

    An entity the registry knows keeps its id; only entities registered
    for the first time get the scheme. Nothing on a running install changes
    by changing the option.
    """
    await _setup(hass, current_entry)
    before = _entity_id(hass, current_entry, "sensor", f"{NODE}_cpu")
    assert before == "sensor.node_pve_cpu_used"

    hass.config_entries.async_update_entry(
        current_entry,
        options={**current_entry.options, CONF_ENTITY_ID_SCHEME: SCHEME_EXTENDED},
    )
    await hass.config_entries.async_reload(current_entry.entry_id)
    await hass.async_block_till_done()

    assert _entity_id(hass, current_entry, "sensor", f"{NODE}_cpu") == before
