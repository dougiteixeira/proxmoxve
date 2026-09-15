# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for tracking a shared storage once, not once per node."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.proxmoxve import DOMAIN
from custom_components.proxmoxve.const import CONF_STORAGE, COORDINATORS, ProxmoxType
from custom_components.proxmoxve.storage import (
    is_shared_storage_id,
    merge_shared_selection,
    shared_storage_names,
    storage_choices,
    storage_name,
    storage_node,
    tracked_storage_ids,
)

from .fake_api import NODE, STORAGE_EXT, STORAGE_EXT_PVE2, STORAGE_LOCAL, FakeProxmox

# A four-node cluster's storage listing, trimmed to what matters: one NFS
# export every node mounts, one local directory per node. Names invented.
LISTING = [
    {
        "id": "storage/n1/nas",
        "storage": "nas",
        "node": "n1",
        "type": "storage",
        "shared": 1,
        "status": "available",
    },
    {
        "id": "storage/n2/nas",
        "storage": "nas",
        "node": "n2",
        "type": "storage",
        "shared": 1,
        "status": "available",
    },
    {
        "id": "storage/n3/nas",
        "storage": "nas",
        "node": "n3",
        "type": "storage",
        "shared": 1,
        "status": "unknown",
    },
    {
        "id": "storage/n1/local",
        "storage": "local",
        "node": "n1",
        "type": "storage",
        "shared": 0,
    },
    {
        "id": "storage/n2/local",
        "storage": "local",
        "node": "n2",
        "type": "storage",
        "shared": 0,
    },
    {"id": "sdn/n1/localnetwork", "type": "sdn", "node": "n1"},
]


def test_the_two_forms_of_id() -> None:
    """Test the node-less form is told apart from the per-node one."""
    assert is_shared_storage_id("storage/nas")
    assert not is_shared_storage_id("storage/n1/nas")
    assert storage_name("storage/n1/nas") == storage_name("storage/nas") == "nas"
    assert storage_node("storage/n1/nas") == "n1"
    assert storage_node("storage/nas") is None


def test_shared_storage_is_tracked_once_and_local_per_node() -> None:
    """Test the listing collapses to one id per shared storage."""
    assert shared_storage_names(LISTING) == {"nas"}
    assert tracked_storage_ids(LISTING) == [
        "storage/n1/local",
        "storage/n2/local",
        "storage/nas",
    ]


def test_the_pick_list_says_which_ones_are_shared() -> None:
    """Test the config flow's choices name shared storage as such, once."""
    assert storage_choices(LISTING) == {
        "storage/n1/local": "storage/n1/local",
        "storage/n2/local": "storage/n2/local",
        "storage/nas": "nas (shared)",
    }


def test_merging_keeps_the_configured_nodes_entry() -> None:
    """
    Test the per-node ids of a shared storage become one, keeping history.

    The entry on the node the configured host is keeps the device and the
    entities under the new id; the others are dropped. Local storage and
    ids already in the new form pass through untouched.
    """
    selection = [
        "storage/n1/local",
        "storage/n1/nas",
        "storage/n2/nas",
        "storage/n3/nas",
    ]

    new, keepers, dropped = merge_shared_selection(selection, {"nas"}, "n2")

    assert new == ["storage/n1/local", "storage/nas"]
    assert keepers == {"storage/nas": "storage/n2/nas"}
    assert dropped == ["storage/n1/nas", "storage/n3/nas"]


def test_merging_without_the_configured_node_keeps_the_first_picked() -> None:
    """Test the first picked entry keeps history when the local node is unknown."""
    new, keepers, dropped = merge_shared_selection(
        ["storage/n3/nas", "storage/n1/nas"], {"nas"}, None
    )

    assert new == ["storage/nas"]
    assert keepers == {"storage/nas": "storage/n3/nas"}
    assert dropped == ["storage/n1/nas"]


def test_a_current_selection_is_left_alone() -> None:
    """Test a selection already in the new form does not change."""
    selection = ["storage/nas", "storage/n1/local"]

    new, keepers, dropped = merge_shared_selection(selection, {"nas"}, "n1")

    assert new == selection
    assert keepers == {}
    assert dropped == []


async def test_a_shared_storage_reads_from_a_node_that_sees_it(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """
    Test the one entity carries the figures and says which nodes see it.

    `ext` is listed by two nodes in the fake cluster with identical figures.
    The row of a node reporting it available answers; both are carried.
    """
    hass.config_entries.async_update_entry(
        current_entry, data={**current_entry.data, CONF_STORAGE: ["storage/ext"]}
    )
    await hass.config_entries.async_setup(current_entry.entry_id)
    await hass.async_block_till_done()
    assert current_entry.state is ConfigEntryState.LOADED

    coordinator = current_entry.runtime_data[COORDINATORS][
        f"{ProxmoxType.Storage}_storage/ext"
    ]
    data = coordinator.data
    assert data.name == "Storage ext"
    assert data.node == NODE
    assert data.nodes == (NODE, "pve2")
    assert data.disk_used == STORAGE_EXT["disk"]

    registry = er.async_get(hass)
    entry_id = current_entry.entry_id
    node_sensor = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry_id}_storage/ext_node"
    )
    assert node_sensor is not None
    assert hass.states.get(node_sensor).attributes["nodes"] == [NODE, "pve2"]

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{entry_id}_STORAGE_ext"), entry_id
    )
    assert device is not None
    assert device.model == "Shared storage"
    cluster = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{entry_id}_cluster"), entry_id
    )
    assert cluster is not None
    assert device.via_device_id == cluster.id


async def test_a_shared_storage_no_node_sees_still_has_an_entity(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test a shared storage every node reports unavailable is still tracked."""
    fake_api.routes["cluster/resources?type=storage"] = [
        {**row, "status": "unknown"} if row["storage"] == "ext" else row
        for row in fake_api.routes["cluster/resources?type=storage"]
    ]
    hass.config_entries.async_update_entry(
        current_entry, data={**current_entry.data, CONF_STORAGE: ["storage/ext"]}
    )
    await hass.config_entries.async_setup(current_entry.entry_id)
    await hass.async_block_till_done()

    data = current_entry.runtime_data[COORDINATORS][
        f"{ProxmoxType.Storage}_storage/ext"
    ].data
    assert data.nodes == ()
    assert data.node == NODE


async def test_an_older_selection_is_merged_at_setup_with_its_history(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """
    Test the reported problem: one shared export shown once per node.

    An entry that picked `ext` on both nodes gets one `storage/ext` device.
    The entry on the node the configured host is keeps the device and the
    entities - same registry ids, new unique ids - and the other one loses
    its device. The selection in the entry is rewritten, and a reload then
    changes nothing more.
    """
    hass.config_entries.async_update_entry(
        current_entry,
        data={
            **current_entry.data,
            CONF_STORAGE: [
                "storage/pve/local",
                "storage/pve2/ext",
                f"storage/{NODE}/ext",
            ],
        },
    )
    entry_id = current_entry.entry_id
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    # What an older version left behind: a device and an entity per node.
    kept_device = dev_reg.async_get_or_create(
        config_entry_id=entry_id,
        identifiers={(DOMAIN, f"{entry_id}_STORAGE_{NODE}/ext")},
    )
    gone_device = dev_reg.async_get_or_create(
        config_entry_id=entry_id, identifiers={(DOMAIN, f"{entry_id}_STORAGE_pve2/ext")}
    )
    kept_entity = ent_reg.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{entry_id}_storage/{NODE}/ext_disk_used_perc",
        config_entry=current_entry,
        device_id=kept_device.id,
    )

    await hass.config_entries.async_setup(current_entry.entry_id)
    await hass.async_block_till_done()
    assert current_entry.state is ConfigEntryState.LOADED

    assert current_entry.data[CONF_STORAGE] == ["storage/pve/local", "storage/ext"]
    merged = dev_reg.async_get_device_by_identifier(
        (DOMAIN, f"{entry_id}_STORAGE_ext"), entry_id
    )
    assert merged is not None
    assert merged.id == kept_device.id
    assert (
        dev_reg.async_get_device_by_identifier(
            (DOMAIN, f"{entry_id}_STORAGE_pve2/ext"), entry_id
        )
        is None
    )
    # The device that lost this entry is gone entirely: it had no other.
    assert dev_reg.async_get(gone_device.id) is None
    moved = ent_reg.async_get(kept_entity.entity_id)
    assert moved is not None
    assert moved.unique_id == f"{entry_id}_storage/ext_disk_used_perc"
    assert (
        ent_reg.async_get_entity_id(
            "sensor", DOMAIN, f"{entry_id}_storage/ext_disk_used_perc"
        )
        == kept_entity.entity_id
    )
    assert (
        f"{ProxmoxType.Storage}_storage/ext" in current_entry.runtime_data[COORDINATORS]
    )
    assert (
        f"{ProxmoxType.Storage}_storage/pve2/ext"
        not in current_entry.runtime_data[COORDINATORS]
    )


def test_the_fixtures_agree_on_the_shared_export() -> None:
    """Test the two rows of the fake's export differ only in node and id."""
    assert {k: v for k, v in STORAGE_EXT.items() if k not in ("id", "node")} == {
        k: v for k, v in STORAGE_EXT_PVE2.items() if k not in ("id", "node")
    }
    assert STORAGE_LOCAL["shared"] == 0
