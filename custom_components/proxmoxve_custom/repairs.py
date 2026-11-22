# ruff: noqa: CPY001
"""Repair flows for the Proxmox VE integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.homeassistant import (
    DOMAIN as HOMEASSISTANT_DOMAIN,
)
from homeassistant.components.homeassistant import SERVICE_HOMEASSISTANT_RESTART
from homeassistant.components.repairs import RepairsFlow, RepairsFlowResult

from .const import ISSUE_DOMAIN_MIGRATION_RESTART

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


class DomainMigrationRestartFlow(RepairsFlow):
    """Confirm a restart after migrating the integration domain."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> RepairsFlowResult:
        """Show the restart confirmation."""
        return await self.async_step_confirm_restart()

    async def async_step_confirm_restart(
        self, user_input: dict[str, Any] | None = None
    ) -> RepairsFlowResult:
        """Restart Home Assistant when the user confirms."""
        if user_input is not None:
            await self.hass.services.async_call(
                HOMEASSISTANT_DOMAIN, SERVICE_HOMEASSISTANT_RESTART, blocking=True
            )
            return self.async_create_entry(title="", data={})
        return self.async_show_form(step_id="confirm_restart")


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None = None,
) -> RepairsFlow:
    """Create the domain migration repair flow."""
    if issue_id == ISSUE_DOMAIN_MIGRATION_RESTART:
        return DomainMigrationRestartFlow()
    message = f"Unknown repair: {issue_id}"
    raise ValueError(message)
