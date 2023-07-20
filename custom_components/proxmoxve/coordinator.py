"""DataUpdateCoordinators for the Proxmox VE integration."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from proxmoxer import AuthenticationError, ProxmoxAPI
from proxmoxer.core import ResourceException
from requests.exceptions import ConnectTimeout, SSLError

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
)
from homeassistant.helpers.typing import UNDEFINED, UndefinedType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_NODE, DOMAIN, LOGGER, UPDATE_INTERVAL, ProxmoxType
from .models import ProxmoxLXCData, ProxmoxNodeData, ProxmoxVMData


class ProxmoxCoordinator(
    DataUpdateCoordinator[ProxmoxNodeData | ProxmoxVMData | ProxmoxLXCData]
):
    """Proxmox VE data update coordinator."""


class ProxmoxNodeCoordinator(ProxmoxCoordinator):
    """Proxmox VE Node data update coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        proxmox: ProxmoxAPI,
        host_name: str,
        node_name: str,
    ) -> None:
        """Initialize the Proxmox Node coordinator."""

        super().__init__(
            hass,
            LOGGER,
            name=f"proxmox_coordinator_{host_name}_{node_name}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

        self.hass = hass
        self.config_entry: ConfigEntry = self.config_entry
        self.proxmox = proxmox
        self.node_name = node_name

    async def _async_update_data(self) -> ProxmoxNodeData:
        """Update data  for Proxmox Node."""

        def poll_api() -> dict[str, Any] | None:
            """Return data from the Proxmox Node API."""
            try:
                api_status = self.proxmox.nodes(self.node_name).status.get()
                if nodes_api := self.proxmox.nodes.get():
                    for node_api in nodes_api:
                        if node_api[CONF_NODE] == self.node_name:
                            api_status["status"] = node_api["status"]
                            api_status["cpu"] = node_api["cpu"]
                            api_status["disk_max"] = node_api["maxdisk"]
                            api_status["disk_used"] = node_api["disk"]
                            break
                api_status["version"] = self.proxmox.nodes(self.node_name).version.get()

            except (
                AuthenticationError,
                SSLError,
                ConnectTimeout,
            ) as error:
                raise UpdateFailed(error) from error
            except ResourceException as error:
                if error.status_code == 403:
                    async_create_issue(
                        self.hass,
                        DOMAIN,
                        f"{self.config_entry.entry_id}_{self.node_name}_forbiden",
                        is_fixable=False,
                        severity=IssueSeverity.ERROR,
                        translation_key="resource_exception_forbiden",
                        translation_placeholders={
                            "resource": f"Node {self.node_name}",
                            "user": self.config_entry.data[CONF_USERNAME],
                        },
                    )
                    raise UpdateFailed(
                        "User not allowed to access the resource, check user permissions as per the documentation."
                    ) from error

            async_delete_issue(
                self.hass,
                DOMAIN,
                f"{self.config_entry.entry_id}_{self.node_name}_forbiden",
            )

            LOGGER.debug("API Response - Node: %s", api_status)
            return api_status

        api_status = await self.hass.async_add_executor_job(poll_api)

        if api_status is None:
            raise UpdateFailed(
                f"Node {self.node_name} unable to be found in host {self.config_entry.data[CONF_HOST]}"
            )

        return ProxmoxNodeData(
            model=api_status["cpuinfo"]["model"],
            status=api_status["status"],
            version=api_status["version"]["version"],
            uptime=api_status["uptime"],
            cpu=api_status["cpu"],
            disk_total=api_status["disk_max"],
            disk_used=api_status["disk_used"],
            memory_total=api_status["memory"]["total"],
            memory_used=api_status["memory"]["used"],
            memory_free=api_status["memory"]["free"],
            swap_total=api_status["swap"]["total"],
            swap_free=api_status["swap"]["free"],
            swap_used=api_status["swap"]["used"],
        )


class ProxmoxQEMUCoordinator(ProxmoxCoordinator):
    """Proxmox VE QEMU data update coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        proxmox: ProxmoxAPI,
        host_name: str,
        qemu_id: int,
    ) -> None:
        """Initialize the Proxmox QEMU coordinator."""

        super().__init__(
            hass,
            LOGGER,
            name=f"proxmox_coordinator_{host_name}_{qemu_id}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

        self.hass = hass
        self.config_entry: ConfigEntry = self.config_entry
        self.proxmox = proxmox
        self.node_name: str
        self.vm_id = qemu_id

    async def _async_update_data(self) -> ProxmoxVMData:
        """Update data  for Proxmox QEMU."""

        def poll_api() -> dict[str, Any] | None:
            """Return data from the Proxmox QEMU API."""
            node_name = None
            try:
                api_status = None

                resources = self.proxmox.cluster.resources.get()
                LOGGER.debug("API Response - Resources: %s", resources)

                for resource in resources:
                    if "vmid" in resource:
                        if int(resource["vmid"]) == int(self.vm_id):
                            node_name = resource["node"]

                self.node_name = str(node_name)
                if self.node_name is not None:
                    api_status = (
                        self.proxmox.nodes(self.node_name)
                        .qemu(self.vm_id)
                        .status.current.get()
                    )

            except (
                AuthenticationError,
                SSLError,
                ConnectTimeout,
            ) as error:
                raise UpdateFailed(error) from error
            except ResourceException as error:
                if error.status_code == 403:
                    async_create_issue(
                        self.hass,
                        DOMAIN,
                        f"{self.config_entry.entry_id}_{self.vm_id}_forbiden",
                        is_fixable=False,
                        severity=IssueSeverity.ERROR,
                        translation_key="resource_exception_forbiden",
                        translation_placeholders={
                            "resource": f"QEMU {self.vm_id}",
                            "user": self.config_entry.data[CONF_USERNAME],
                        },
                    )
                    raise UpdateFailed(
                        "User not allowed to access the resource, check user permissions as per the documentation."
                    ) from error

            async_delete_issue(
                self.hass,
                DOMAIN,
                f"{self.config_entry.entry_id}_{self.vm_id}_forbiden",
            )

            LOGGER.debug("API Response - QEMU: %s", api_status)
            return api_status

        api_status = await self.hass.async_add_executor_job(poll_api)

        if api_status is None or "status" not in api_status:
            raise UpdateFailed(f"Vm/Container {self.vm_id} unable to be found")

        update_device_via(self, ProxmoxType.QEMU)
        return ProxmoxVMData(
            status=api_status["status"],
            name=api_status["name"],
            node=self.node_name,
            health=api_status["qmpstatus"],
            uptime=api_status["uptime"],
            cpu=api_status["cpu"],
            memory_total=api_status["maxmem"],
            memory_used=api_status["mem"],
            memory_free=api_status["maxmem"] - api_status["mem"],
            network_in=api_status["netin"],
            network_out=api_status["netout"],
            disk_total=api_status["maxdisk"],
            disk_used=api_status["disk"],
        )


class ProxmoxLXCCoordinator(ProxmoxCoordinator):
    """Proxmox VE LXC data update coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        proxmox: ProxmoxAPI,
        host_name: str,
        container_id: int,
    ) -> None:
        """Initialize the Proxmox LXC coordinator."""

        super().__init__(
            hass,
            LOGGER,
            name=f"proxmox_coordinator_{host_name}_{container_id}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

        self.hass = hass
        self.config_entry: ConfigEntry = self.config_entry
        self.proxmox = proxmox
        self.vm_id = container_id
        self.node_name: str

    async def _async_update_data(self) -> ProxmoxLXCData:
        """Update data  for Proxmox LXC."""

        def poll_api() -> dict[str, Any] | None:
            """Return data from the Proxmox LXC API."""
            node_name = None
            try:
                api_status = None

                resources = self.proxmox.cluster.resources.get()
                LOGGER.debug("API Response - Resources: %s", resources)

                for resource in resources:
                    if "vmid" in resource:
                        if int(resource["vmid"]) == int(self.vm_id):
                            node_name = resource["node"]

                self.node_name = str(node_name)
                if node_name is not None:
                    api_status = (
                        self.proxmox.nodes(self.node_name)
                        .lxc(self.vm_id)
                        .status.current.get()
                    )

            except (
                AuthenticationError,
                SSLError,
                ConnectTimeout,
            ) as error:
                raise UpdateFailed(error) from error
            except ResourceException as error:
                if error.status_code == 403:
                    async_create_issue(
                        self.hass,
                        DOMAIN,
                        f"{self.config_entry.entry_id}_{self.vm_id}_forbiden",
                        is_fixable=False,
                        severity=IssueSeverity.ERROR,
                        translation_key="resource_exception_forbiden",
                        translation_placeholders={
                            "resource": f"LXC {self.node_name}",
                            "user": self.config_entry.data[CONF_USERNAME],
                        },
                    )
                    raise UpdateFailed(
                        "User not allowed to access the resource, check user permissions as per the documentation."
                    ) from error

            async_delete_issue(
                self.hass,
                DOMAIN,
                f"{self.config_entry.entry_id}_{self.vm_id}_forbiden",
            )

            LOGGER.debug("API Response - LXC: %s", api_status)
            return api_status

        api_status = await self.hass.async_add_executor_job(poll_api)

        if api_status is None or "status" not in api_status:
            raise UpdateFailed(f"Vm/Container {self.vm_id} unable to be found")

        update_device_via(self, ProxmoxType.LXC)
        return ProxmoxLXCData(
            status=api_status["status"],
            name=api_status["name"],
            node=self.node_name,
            uptime=api_status["uptime"],
            cpu=api_status["cpu"],
            memory_total=api_status["maxmem"],
            memory_used=api_status["mem"],
            memory_free=api_status["maxmem"] - api_status["mem"],
            network_in=api_status["netin"],
            network_out=api_status["netout"],
            disk_total=api_status["maxdisk"],
            disk_used=api_status["disk"],
            swap_total=api_status["maxswap"],
            swap_used=api_status["swap"],
            swap_free=api_status["maxswap"] - api_status["swap"],
        )


def update_device_via(
    self,
    api_category: ProxmoxType,
) -> None:
    """Return the Device Info."""
    dev_reg = dr.async_get(self.hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=self.config_entry.entry_id,
        identifiers={
            (
                DOMAIN,
                f"{self.config_entry.entry_id}_{api_category.upper()}_{self.vm_id}",
            )
        },
    )
    via_device = dev_reg.async_get_device(
        {
            (
                DOMAIN,
                f"{self.config_entry.entry_id}_{ProxmoxType.Node.upper()}_{self.node_name}",
            )
        }
    )
    via_device_id: str | UndefinedType = via_device.id if via_device else UNDEFINED
    if device.via_device_id != via_device_id:
        LOGGER.debug(
            "Update device %s - connected via device: old=%s, new=%s",
            self.vm_id,
            device.via_device_id,
            via_device_id,
        )
        dev_reg.async_update_device(
            device.id,
            via_device_id=via_device_id,
            entry_type=dr.DeviceEntryType.SERVICE,
        )


async def verify_permissions_error(
    self,
    resource_type: ProxmoxType,
    resource: str,
    resource_node: str | None = None,
) -> bool:
    """Check the minimum permissions for the user."""
    permissions: bool = False
    if resource_type == ProxmoxType.Node:
        try:
            self.proxmox.nodes(resource).status.get()
        except ResourceException as error:
            if error.status_code == 403:
                permissions = True
    if resource_type == ProxmoxType.QEMU:
        try:
            self.proxmox.nodes(resource_node).qemu(resource).get()
        except ResourceException as error:
            if error.status_code == 403:
                permissions = True

    if resource_type == ProxmoxType.LXC:
        try:
            self.proxmox.nodes(resource_node).lxc(resource).get()
        except ResourceException as error:
            if error.status_code == 403:
                permissions = True

    if permissions:
        async_create_issue(
            self.hass,
            DOMAIN,
            f"{self.config_entry.entry_id}_{resource}_forbiden",
            is_fixable=False,
            severity=IssueSeverity.ERROR,
            translation_key="resource_exception_forbiden",
            translation_placeholders={
                "resource": f"{resource_type.upper()} {resource}",
                "user": self.config_entry.data[CONF_USERNAME],
            },
        )
    return permissions
