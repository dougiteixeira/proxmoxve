# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""
Tests for reading the QEMU guest agent without the privilege for it.

Reported upstream as #676: `agent/get-fsinfo` needs `VM.GuestAgent.Audit`
since Proxmox VE 9, and the repair blamed `VM.Audit` - which the
credentials held - under the same id as the guest's own repair, so the
status read cleared what the agent read had just raised, once a minute.
The privilege is missing for every VM at once, so there is one repair per
feature listing the VMs, not one per VM.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from proxmoxer.core import ResourceException
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.proxmoxve import DOMAIN
from custom_components.proxmoxve.const import (
    CONF_GUEST_FILE_PATH,
    CONF_QEMU,
    COORDINATORS,
)

from .fake_api import NODE, FakeProxmox, add_guest
from .test_setup_full import _setup, _state

FORBIDDEN = ResourceException(
    403, "Forbidden", "Permission check failed (/vms/101, VM.GuestAgent.Audit)"
)
FSINFO = f"nodes/{NODE}/qemu/101/agent/get-fsinfo"


def _issue(
    hass: HomeAssistant, entry: MockConfigEntry, suffix: str
) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(DOMAIN, f"{entry.entry_id}_{suffix}")


async def test_a_refused_agent_read_raises_one_repair_naming_the_privilege(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test the repair names the guest agent privilege and the VM, not VM.Audit."""
    fake_api.routes[FSINFO] = FORBIDDEN
    await _setup(hass, current_entry)

    issue = _issue(hass, current_entry, "guest_agent_fsinfo")
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_key == "guest_agent_fsinfo_forbidden"
    assert "VM.GuestAgent.Audit" in issue.translation_placeholders["permission"]
    assert issue.translation_placeholders["vms"] == "101"
    # The guest's own repair - the VM.Audit one - is not raised: the status
    # read succeeded, and the VM is set up as usual.
    assert _issue(hass, current_entry, "forbidden") is None
    status = _state(
        hass, current_entry, f"{current_entry.entry_id}_101_status_raw", "sensor"
    )
    assert status.state == "running"


async def test_every_refused_vm_joins_the_same_repair(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test two VMs without the privilege make one repair listing both."""
    add_guest(fake_api.routes, "qemu", 102, "vm-test-102")
    fake_api.routes[FSINFO] = FORBIDDEN
    fake_api.routes[f"nodes/{NODE}/qemu/102/agent/get-fsinfo"] = FORBIDDEN
    hass.config_entries.async_update_entry(
        current_entry, data={**current_entry.data, CONF_QEMU: ["101", "102"]}
    )
    await _setup(hass, current_entry)

    issues = [
        issue
        for issue in ir.async_get(hass).issues.values()
        if issue.domain == DOMAIN and "guest_agent" in issue.issue_id
    ]
    assert len(issues) == 1
    assert issues[0].translation_placeholders["vms"] == "101, 102"


async def test_the_repair_follows_the_reads(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test the guest's status poll does not clear it; a working read does."""
    working = fake_api.routes[FSINFO]
    fake_api.routes[FSINFO] = FORBIDDEN
    await _setup(hass, current_entry)
    coordinator = current_entry.runtime_data[COORDINATORS]["qemu_101"]

    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert _issue(hass, current_entry, "guest_agent_fsinfo") is not None

    fake_api.routes[FSINFO] = working
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert _issue(hass, current_entry, "guest_agent_fsinfo") is None


async def test_the_file_sensor_has_a_repair_of_its_own(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test file-read without VM.GuestAgent.FileRead says so, separately."""
    hass.config_entries.async_update_entry(
        current_entry,
        options={**current_entry.options, CONF_GUEST_FILE_PATH: "/etc/hostname"},
    )
    fake_api.routes[
        f"nodes/{NODE}/qemu/101/agent/file-read?file=%2Fetc%2Fhostname&count=4096&decode=1"
    ] = ResourceException(403, "Forbidden", "Permission check failed")
    await _setup(hass, current_entry)

    issue = _issue(hass, current_entry, "guest_agent_file")
    assert issue is not None
    assert issue.translation_key == "guest_agent_file_forbidden"
    assert "VM.GuestAgent.FileRead" in issue.translation_placeholders["permission"]
    assert _issue(hass, current_entry, "guest_agent_fsinfo") is None
    assert _issue(hass, current_entry, "forbidden") is None
