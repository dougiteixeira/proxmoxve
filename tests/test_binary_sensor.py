# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for the Proxmox VE binary sensors."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.proxmoxve.binary_sensor import (
    PROXMOX_BINARYSENSOR_VM,
    ProxmoxBinarySensorEntity,
    ProxmoxBinarySensorEntityDescription,
)
from custom_components.proxmoxve.button import PROXMOX_BUTTON_VM
from custom_components.proxmoxve.const import (
    ProxmoxCommand,
    ProxmoxKeyAPIParse,
    ProxmoxType,
)


def _locked_description() -> ProxmoxBinarySensorEntityDescription:
    """Return the 'Locked' binary sensor description."""
    return next(
        description
        for description in PROXMOX_BINARYSENSOR_VM
        if description.key == ProxmoxKeyAPIParse.LOCKED
    )


def _locked_binary_sensor(*, locked: bool) -> ProxmoxBinarySensorEntity:
    """Build a Locked binary sensor backed by a guest with the given lock state."""
    coordinator = MagicMock()
    coordinator.data = SimpleNamespace(locked=locked)
    return ProxmoxBinarySensorEntity(
        coordinator=coordinator,
        unique_id="test_locked",
        info_device={},
        description=_locked_description(),
    )


def test_locked_binary_sensor_is_on() -> None:
    """Test the Locked binary sensor reflects the guest lock state."""
    assert _locked_binary_sensor(locked=True).is_on is True
    assert _locked_binary_sensor(locked=False).is_on is False


def test_unlock_button_is_qemu_only() -> None:
    """Test the unlock button is registered for QEMU VMs only (LXC has no API unlock)."""
    unlock = next(
        description
        for description in PROXMOX_BUTTON_VM
        if description.key == ProxmoxCommand.UNLOCK
    )
    assert unlock.api_category is ProxmoxType.QEMU
