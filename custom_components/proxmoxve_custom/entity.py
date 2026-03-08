"""Proxmox parent entity class."""

import dataclasses

from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)


@dataclasses.dataclass(frozen=True, kw_only=True)
class ProxmoxEntityDescription(EntityDescription):
    """Describe a Proxmox entity."""


class ProxmoxEntity(CoordinatorEntity):
    """Represents any entity created for the Proxmox VE platform."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        unique_id: str,
        description: ProxmoxEntityDescription,
    ) -> None:
        """Initialize the Proxmox entity."""
        super().__init__(coordinator)

        self.coordinator = coordinator
        self.entity_description = description
        self._attr_unique_id = unique_id

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success
