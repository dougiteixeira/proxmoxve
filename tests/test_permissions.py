# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for leaving out buttons the credentials could never use."""

from unittest.mock import MagicMock, patch

from homeassistant.core import HomeAssistant
from proxmoxer.core import ResourceException

from custom_components.proxmoxve.button import (
    PROXMOX_BUTTON_CLUSTER,
    PROXMOX_BUTTON_NODE,
    PROXMOX_BUTTON_VM,
    button_permitted,
)
from custom_components.proxmoxve.const import ProxmoxCommand, ProxmoxType
from custom_components.proxmoxve.permissions import (
    ProxmoxPrivilege,
    async_fetch_permissions,
    is_granted,
    is_granted_anywhere_below,
)

# Shaped like `GET /access/permissions` for a token that may audit the whole
# cluster, control VM 100 and snapshot VM 101, and power-manage node pve1.
PERMISSIONS = {
    "/": {"Sys.Audit": 1, "VM.Audit": 1, "Datastore.Audit": 1},
    "/nodes/pve1": {"Sys.PowerMgmt": 1, "Sys.Audit": 1},
    "/vms/100": {"VM.PowerMgmt": 1, "VM.Audit": 1},
    "/vms/101": {"VM.Snapshot": 1, "VM.Audit": 1},
}


def _button(descriptions: tuple, key: ProxmoxCommand):  # noqa: ANN202
    """Return the button description with the given command."""
    return next(d for d in descriptions if d.key == key)


def test_a_grant_on_the_path_itself() -> None:
    """Test the plain case."""
    assert is_granted(PERMISSIONS, "/vms/100", "VM.PowerMgmt")
    assert not is_granted(PERMISSIONS, "/vms/101", "VM.PowerMgmt")


def test_a_grant_propagates_down() -> None:
    """Test a privilege on `/` or `/vms` covers every guest."""
    assert is_granted(PERMISSIONS, "/vms/999", "VM.Audit")
    assert is_granted({"/vms": {"VM.PowerMgmt": 1}}, "/vms/7", "VM.PowerMgmt")


def test_a_grant_does_not_propagate_up_or_sideways() -> None:
    """Test power on one node says nothing about another, or about `/`."""
    assert not is_granted(PERMISSIONS, "/nodes/pve2", "Sys.PowerMgmt")
    assert not is_granted(PERMISSIONS, "/", "Sys.PowerMgmt")


def test_zero_is_not_a_grant() -> None:
    """Test an explicit 0 - the API's way of saying denied - is denied."""
    assert not is_granted({"/vms/100": {"VM.PowerMgmt": 0}}, "/vms/100", "VM.PowerMgmt")


def test_anything_below_counts_for_the_bulk_actions() -> None:
    """Test power on one guest is enough for `startall` to do something."""
    assert is_granted_anywhere_below(PERMISSIONS, "/vms", "VM.PowerMgmt")
    assert not is_granted_anywhere_below(PERMISSIONS, "/vms", "Sys.PowerMgmt")
    assert not is_granted_anywhere_below({}, "/vms", "VM.PowerMgmt")


def test_vm_buttons_follow_the_guest_privileges() -> None:
    """Test each guest gets exactly the buttons its privileges allow."""
    start = _button(PROXMOX_BUTTON_VM, ProxmoxCommand.START)
    snapshot = _button(PROXMOX_BUTTON_VM, ProxmoxCommand.SNAPSHOT)

    assert button_permitted(PERMISSIONS, start, ProxmoxType.QEMU, 100)
    assert not button_permitted(PERMISSIONS, snapshot, ProxmoxType.QEMU, 100)
    assert not button_permitted(PERMISSIONS, start, ProxmoxType.LXC, 101)
    assert button_permitted(PERMISSIONS, snapshot, ProxmoxType.LXC, 101)


def test_node_buttons_tell_node_power_from_guest_power() -> None:
    """
    Test reboot needs Sys.PowerMgmt on the node, start-all VM.PowerMgmt on a guest.

    Proxmox checks the bulk actions per guest, so a node the credentials may
    not reboot can still get a `Start all` button.
    """
    reboot = _button(PROXMOX_BUTTON_NODE, ProxmoxCommand.REBOOT)
    start_all = _button(PROXMOX_BUTTON_NODE, ProxmoxCommand.START_ALL)

    assert button_permitted(PERMISSIONS, reboot, ProxmoxType.Node, "pve1")
    assert not button_permitted(PERMISSIONS, reboot, ProxmoxType.Node, "pve2")
    assert button_permitted(PERMISSIONS, start_all, ProxmoxType.Node, "pve2")
    assert not button_permitted(
        {"/": {"Sys.Audit": 1}}, start_all, ProxmoxType.Node, "pve1"
    )


def test_cluster_buttons_need_console_on_root() -> None:
    """Test arm/disarm are gated on Sys.Console at `/`, nothing less."""
    arm = _button(PROXMOX_BUTTON_CLUSTER, ProxmoxCommand.ARM_HA)

    assert not button_permitted(PERMISSIONS, arm, ProxmoxType.Proxmox, "cluster")
    assert button_permitted(
        {"/": {"Sys.Console": 1}}, arm, ProxmoxType.Proxmox, "cluster"
    )
    assert not button_permitted(
        {"/nodes/pve1": {"Sys.Console": 1}}, arm, ProxmoxType.Proxmox, "cluster"
    )


def test_unknown_permissions_gate_nothing() -> None:
    """Test buttons are all created when the permissions could not be read."""
    snapshot = _button(PROXMOX_BUTTON_VM, ProxmoxCommand.SNAPSHOT)

    assert button_permitted(None, snapshot, ProxmoxType.QEMU, 100)


def test_every_button_names_its_privilege() -> None:
    """Test no button slipped in without saying what it needs."""
    for descriptions in (
        PROXMOX_BUTTON_NODE,
        PROXMOX_BUTTON_VM,
        PROXMOX_BUTTON_CLUSTER,
    ):
        for description in descriptions:
            assert isinstance(description.privilege, ProxmoxPrivilege), description.key


async def test_fetch_permissions_reads_the_mapping(hass: HomeAssistant) -> None:
    """Test the API's answer is kept as path -> privilege -> 0/1."""
    proxmox = MagicMock()
    proxmox.get.return_value = PERMISSIONS

    assert await async_fetch_permissions(hass, proxmox) == PERMISSIONS
    proxmox.get.assert_called_once_with("access/permissions")


async def test_fetch_permissions_when_the_call_fails(hass: HomeAssistant) -> None:
    """Test a failed call yields None rather than an empty mapping - which would gate everything."""
    proxmox = MagicMock()
    proxmox.get.side_effect = ResourceException(500, "boom", "no")

    assert await async_fetch_permissions(hass, proxmox) is None


async def test_fetch_permissions_with_an_unexpected_answer(
    hass: HomeAssistant,
) -> None:
    """Test something that is not a mapping is treated as unknown."""
    proxmox = MagicMock()
    proxmox.get.return_value = [{"vmid": 100}]

    with patch("custom_components.proxmoxve.permissions.LOGGER"):
        assert await async_fetch_permissions(hass, proxmox) is None
