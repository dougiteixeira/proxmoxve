# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""
Tests for asking the QEMU guest agent only when it can answer.

Proxmox answers every `agent/*` read with a 500 while the agent is not
enabled for the VM or the VM is not running, so polling a stopped VM's agent
only fills the Proxmox access log with failed requests.
"""

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.proxmoxve.const import COORDINATORS

from .fake_api import NODE, FakeProxmox, qemu_status
from .test_setup_full import _setup

AGENT_PATH = f"nodes/{NODE}/qemu/101/agent/"


def _agent_reads(fake_api: FakeProxmox) -> list[str]:
    """Return the agent reads made for VM 101."""
    return [path for path in fake_api.paths() if path.startswith(AGENT_PATH)]


async def test_a_stopped_vm_is_not_asked_through_its_agent(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test a stopped VM with the agent enabled gets no agent read, and says no."""
    fake_api.routes[f"nodes/{NODE}/qemu/101/status/current"] = qemu_status(
        101, "vm-test-101", status="stopped"
    )
    await _setup(hass, current_entry)

    assert _agent_reads(fake_api) == []
    data = current_entry.runtime_data[COORDINATORS]["qemu_101"].data
    assert data.agent_running is False


async def test_a_paused_vm_is_not_asked_through_its_agent(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test `status: running` alone is not enough: a paused VM's agent is frozen."""
    status = qemu_status(101, "vm-test-101")
    status["qmpstatus"] = "paused"
    fake_api.routes[f"nodes/{NODE}/qemu/101/status/current"] = status
    await _setup(hass, current_entry)

    assert _agent_reads(fake_api) == []
    data = current_entry.runtime_data[COORDINATORS]["qemu_101"].data
    assert data.agent_running is False


async def test_a_vm_without_the_agent_enabled_gets_no_agent_read_at_all(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test the filesystem read is skipped too, not only the interfaces."""
    status = qemu_status(101, "vm-test-101")
    del status["agent"]
    fake_api.routes[f"nodes/{NODE}/qemu/101/status/current"] = status
    await _setup(hass, current_entry)

    assert _agent_reads(fake_api) == []


async def test_a_running_vm_with_its_agent_is_still_asked(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test the guard leaves a reachable agent alone."""
    await _setup(hass, current_entry)

    reads = _agent_reads(fake_api)
    assert f"{AGENT_PATH}get-fsinfo" in reads
    assert f"{AGENT_PATH}network-get-interfaces" in reads
    data = current_entry.runtime_data[COORDINATORS]["qemu_101"].data
    assert data.agent_running is True
