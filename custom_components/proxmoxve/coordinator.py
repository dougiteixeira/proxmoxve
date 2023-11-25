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
from .models import ProxmoxDiskData, ProxmoxLXCData, ProxmoxNodeData, ProxmoxStorageData, ProxmoxUpdateData, ProxmoxVMData


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
        api_category: str,
        node_name: str,
    ) -> None:
        """Initialize the Proxmox Node coordinator."""

        super().__init__(
            hass,
            LOGGER,
            name=f"proxmox_coordinator_{api_category}_{node_name}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

        self.hass = hass
        self.config_entry: ConfigEntry = self.config_entry
        self.proxmox = proxmox
        self.resource_id = node_name

    async def _async_update_data(self) -> ProxmoxNodeData:
        """Update data  for Proxmox Node."""

        def poll_api() -> dict[str, Any] | None:
            """Return data from the Proxmox Node API."""
            try:
                api_status = self.proxmox.nodes(self.resource_id).status.get()
                if nodes_api := self.proxmox.nodes.get():
                    for node_api in nodes_api:
                        if node_api[CONF_NODE] == self.resource_id:
                            api_status["status"] = node_api["status"]
                            api_status["cpu"] = node_api["cpu"]
                            api_status["disk_max"] = node_api["maxdisk"]
                            api_status["disk_used"] = node_api["disk"]
                            break
                api_status["version"] = self.proxmox.nodes(self.resource_id).version.get()

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
                        f"{self.config_entry.entry_id}_{self.resource_id}_forbiden",
                        is_fixable=False,
                        severity=IssueSeverity.ERROR,
                        translation_key="resource_exception_forbiden",
                        translation_placeholders={
                            "resource": f"Node {self.resource_id}",
                            "user": self.config_entry.data[CONF_USERNAME],
                            "permission": f"['perm','/nodes/{self.resource_id}',['Sys.Audit']]"
                        },
                    )
                    raise UpdateFailed(
                        "User not allowed to access the resource, check user permissions as per the documentation, see details in the repair created by the integration."
                    ) from error

            async_delete_issue(
                self.hass,
                DOMAIN,
                f"{self.config_entry.entry_id}_{self.resource_id}_forbiden",
            )

            LOGGER.debug("API Response - Node: %s", api_status)
            return api_status

        api_status = await self.hass.async_add_executor_job(poll_api)

        if api_status is None:
            raise UpdateFailed(
                f"Node {self.resource_id} unable to be found in host {self.config_entry.data[CONF_HOST]}"
            )

        return ProxmoxNodeData(
            type=ProxmoxType.Node,
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
        api_category: str,
        qemu_id: int,
    ) -> None:
        """Initialize the Proxmox QEMU coordinator."""

        super().__init__(
            hass,
            LOGGER,
            name=f"proxmox_coordinator_{api_category}_{qemu_id}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

        self.hass = hass
        self.config_entry: ConfigEntry = self.config_entry
        self.proxmox = proxmox
        self.node_name: str
        self.resource_id = qemu_id

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
                        if int(resource["vmid"]) == int(self.resource_id):
                            node_name = resource["node"]

                self.node_name = str(node_name)
                if self.node_name is not None:
                    api_status = (
                        self.proxmox.nodes(self.node_name)
                        .qemu(self.resource_id)
                        .status.current.get()
                    )

                if node_name is None:
                    raise UpdateFailed(f"{self.resource_id} QEMU node not found")

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
                        f"{self.config_entry.entry_id}_{self.resource_id}_forbiden",
                        is_fixable=False,
                        severity=IssueSeverity.ERROR,
                        translation_key="resource_exception_forbiden",
                        translation_placeholders={
                            "resource": f"QEMU {self.resource_id}",
                            "user": self.config_entry.data[CONF_USERNAME],
                            "permission": "['perm','/vms/{self.resource_id}',['VM.Audit']]"
                        },
                    )
                    raise UpdateFailed(
                        "User not allowed to access the resource, check user permissions as per the documentation, see details in the repair created by the integration."
                    ) from error

            async_delete_issue(
                self.hass,
                DOMAIN,
                f"{self.config_entry.entry_id}_{self.resource_id}_forbiden",
            )

            LOGGER.debug("API Response - QEMU: %s", api_status)
            return api_status

        api_status = await self.hass.async_add_executor_job(poll_api)

        if api_status is None or "status" not in api_status:
            raise UpdateFailed(f"Vm/Container {self.resource_id} unable to be found")

        update_device_via(self, ProxmoxType.QEMU)
        return ProxmoxVMData(
            type=ProxmoxType.QEMU,
            status= api_status["lock"] if ("lock" in api_status and api_status["lock"] == "suspended") else api_status["status"],
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
        api_category: str,
        container_id: int,
    ) -> None:
        """Initialize the Proxmox LXC coordinator."""

        super().__init__(
            hass,
            LOGGER,
            name=f"proxmox_coordinator_{api_category}_{container_id}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

        self.hass = hass
        self.config_entry: ConfigEntry = self.config_entry
        self.proxmox = proxmox
        self.node_name: str
        self.resource_id = container_id

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
                        if int(resource["vmid"]) == int(self.resource_id):
                            node_name = resource["node"]

                self.node_name = str(node_name)
                if node_name is not None:
                    api_status = (
                        self.proxmox.nodes(self.node_name)
                        .lxc(self.resource_id)
                        .status.current.get()
                    )

                if node_name is None:
                    raise UpdateFailed(f"{self.resource_id} LXC node not found")

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
                        f"{self.config_entry.entry_id}_{self.resource_id}_forbiden",
                        is_fixable=False,
                        severity=IssueSeverity.ERROR,
                        translation_key="resource_exception_forbiden",
                        translation_placeholders={
                            "resource": f"LXC {self.resource_id}",
                            "user": self.config_entry.data[CONF_USERNAME],
                            "permission": "['perm','/vms/{self.resource_id}',['VM.Audit']]"
                        },
                    )
                    raise UpdateFailed(
                        "User not allowed to access the resource, check user permissions as per the documentation, see details in the repair created by the integration."
                    ) from error

            async_delete_issue(
                self.hass,
                DOMAIN,
                f"{self.config_entry.entry_id}_{self.resource_id}_forbiden",
            )

            LOGGER.debug("API Response - LXC: %s", api_status)
            return api_status

        api_status = await self.hass.async_add_executor_job(poll_api)

        if api_status is None or "status" not in api_status:
            raise UpdateFailed(f"Vm/Container {self.resource_id} unable to be found")

        update_device_via(self, ProxmoxType.LXC)
        return ProxmoxLXCData(
            type=ProxmoxType.LXC,
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


class ProxmoxStorageCoordinator(ProxmoxCoordinator):
    """Proxmox VE Storage data update coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        proxmox: ProxmoxAPI,
        api_category: str,
        storage_id: str,
    ) -> None:
        """Initialize the Proxmox LXC coordinator."""

        super().__init__(
            hass,
            LOGGER,
            name=f"proxmox_coordinator_{api_category}_{storage_id}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

        self.hass = hass
        self.config_entry: ConfigEntry = self.config_entry
        self.proxmox = proxmox
        self.node_name: str
        self.resource_id = storage_id

    async def _async_update_data(self) -> ProxmoxLXCData:
        """Update data  for Proxmox Update."""

        def poll_api() -> dict[str, Any] | None:
            """Return data from the Proxmox Update API."""
            node_name = None
            try:
                api_status = None

                resources = self.proxmox.cluster.resources.get()
                LOGGER.debug("API Response - Resources: %s", resources)

                for resource in resources:
                    if "storage" in resource:
                        if resource["storage"] == self.resource_id:
                            node_name = resource["node"]

                self.node_name = str(node_name)
                if node_name is not None:
                    api_status = (
                        self.proxmox.nodes(self.node_name)
                        .storage(self.resource_id)
                        .status.get()
                    )

                if node_name is None:
                    raise UpdateFailed(f"{self.resource_id} storage node not found")

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
                        f"{self.config_entry.entry_id}_{self.resource_id}_forbiden",
                        is_fixable=False,
                        severity=IssueSeverity.ERROR,
                        translation_key="resource_exception_forbiden",
                        translation_placeholders={
                            "resource": f"Storage {self.resource_id}",
                            "user": self.config_entry.data[CONF_USERNAME],
                            "permission": f"['perm','/storage/{self.resource_id}',['Datastore.Audit'],'any',1]"
                        },
                    )
                    raise UpdateFailed(
                        "User not allowed to access the resource, check user permissions as per the documentation, see details in the repair created by the integration."
                    ) from error

            async_delete_issue(
                self.hass,
                DOMAIN,
                f"{self.config_entry.entry_id}_{self.resource_id}_forbiden",
            )

            LOGGER.debug("API Response - Storage: %s", api_status)
            return api_status

        api_status = await self.hass.async_add_executor_job(poll_api)

        if api_status is None or "content" not in api_status:
           raise UpdateFailed(f"Storage {self.resource_id} unable to be found")

        update_device_via(self, ProxmoxType.Storage)
        return ProxmoxStorageData(
            type=ProxmoxType.Storage,
            node=self.node_name,
            disk_total=api_status["total"],
            disk_used=api_status["used"],
            disk_free=api_status["avail"],
            content=api_status["content"]
        )

class ProxmoxUpdateCoordinator(ProxmoxCoordinator):
    """Proxmox VE Update data update coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        proxmox: ProxmoxAPI,
        api_category: str,
        node_name: int,
    ) -> None:
        """Initialize the Proxmox LXC coordinator."""

        super().__init__(
            hass,
            LOGGER,
            name=f"proxmox_coordinator_{api_category}_{node_name}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

        self.hass = hass
        self.config_entry: ConfigEntry = self.config_entry
        self.proxmox = proxmox
        self.node_name = node_name
        self.resource_id = f"{api_category}_{node_name}"

    async def _async_update_data(self) -> ProxmoxLXCData:
        """Update data  for Proxmox LXC."""

        def poll_api() -> dict[str, Any] | None:
            """Return data from the Proxmox LXC API."""
            try:
                api_status = None

                if self.node_name is not None:
                    api_status = (
                        self.proxmox.nodes(self.node_name)
                        .apt
                        .update.get()
                    )

                if self.node_name is None:
                    raise UpdateFailed(f"{self.resource_id} node not found")

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
                        f"{self.config_entry.entry_id}_{self.resource_id}_forbiden",
                        is_fixable=False,
                        severity=IssueSeverity.ERROR,
                        translation_key="resource_exception_forbiden",
                        translation_placeholders={
                            "resource": f"Update {self.node_name}",
                            "user": self.config_entry.data[CONF_USERNAME],
                            "permission": f"['perm','/nodes/{self.node_name}',['Sys.Modify']]"
                        },
                    )
                    raise UpdateFailed(
                        "User not allowed to access the resource, check user permissions as per the documentation, see details in the repair created by the integration."
                    ) from error

            async_delete_issue(
                self.hass,
                DOMAIN,
                f"{self.config_entry.entry_id}_{self.resource_id}_forbiden",
            )

            LOGGER.debug("API Response - Update: %s", api_status)
            return api_status

        api_status = await self.hass.async_add_executor_job(poll_api)

        if api_status is None:
            return ProxmoxUpdateData(
                type=ProxmoxType.Update,
                node=self.node_name,
                total=0,
                updates_list=[],
                update=False,
            )

        list = []
        total = 0
        for update in api_status:
            list.append(f"{update['Title']} - {update['Version']}")
            total += 1

        list.sort()

        update_avail=False
        if total >0:
            update_avail=True

        return ProxmoxUpdateData(
            type=ProxmoxType.Update,
            node=self.node_name,
            total=total,
            updates_list=list,
            update=update_avail,
        )

class ProxmoxDiskCoordinator(ProxmoxCoordinator):
    """Proxmox VE Update data disk coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        proxmox: ProxmoxAPI,
        api_category: str,
        node_name: str,
        disk_id: str
    ) -> None:
        """Initialize the Proxmox Disk coordinator."""

        super().__init__(
            hass,
            LOGGER,
            name=f"proxmox_coordinator_{api_category}_{node_name}_{disk_id}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

        self.hass = hass
        self.config_entry: ConfigEntry = self.config_entry
        self.proxmox = proxmox
        self.node_name = node_name
        self.resource_id = disk_id

    async def _async_update_data(self) -> ProxmoxLXCData:
        """Update data  for Proxmox Disk."""

        def poll_api() -> dict[str, Any] | None:
            """Return data from the Proxmox Disk API."""
            try:
                api_status = None

                if self.node_name is None:
                    raise UpdateFailed(f"{self.resource_id} node not found")

                api_status = (
                    self.proxmox.nodes(self.node_name)
                    .disks
                    .list.get()
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
                        f"{self.config_entry.entry_id}_{self.resource_id}_forbiden",
                        is_fixable=False,
                        severity=IssueSeverity.ERROR,
                        translation_key="resource_exception_forbiden",
                        translation_placeholders={
                            "resource": f"Disk {self.node_name}/{self.resource_id}",
                            "user": self.config_entry.data[CONF_USERNAME],
                            "permission": f"['perm','/nodes/{self.node_name}',['Sys.Modify']]"
                        },
                    )
                    raise UpdateFailed(
                        "User not allowed to access the resource, check user permissions as per the documentation, see details in the repair created by the integration."
                    ) from error

            async_delete_issue(
                self.hass,
                DOMAIN,
                f"{self.config_entry.entry_id}_{self.resource_id}_forbiden",
            )

            LOGGER.debug("API Response - Disk: %s", api_status)
            return api_status


        def poll_api_attributes() -> dict[str, Any] | None:
            """Return data from the Proxmox Disk Attributes API."""
            try:
                disk_attributes = None

                if self.node_name is None:
                    raise UpdateFailed(f"{self.resource_id} node not found")

                disk_attributes = (
                    self.proxmox.nodes(self.node_name)
                    .disks
                    .smart.get(disk=self.resource_id)
                )

            except (
                AuthenticationError,
                SSLError,
                ConnectTimeout,
                ResourceException,
            ) as error:
                raise UpdateFailed(error) from error

            LOGGER.debug("API Response - Disk attributes: %s", disk_attributes)
            return disk_attributes

        api_status = await self.hass.async_add_executor_job(poll_api)

        if api_status is None:
            raise UpdateFailed("No data returned.")

        for disk in api_status:
            if disk["devpath"] == self.resource_id:
                disk_attributes = {}
                disk_attributes_api = await self.hass.async_add_executor_job(poll_api_attributes)

                attributes_json = []
                if "attributes" in disk_attributes_api:
                    attributes_json = disk_attributes_api["attributes"]
                else:
                    if "type" in disk_attributes_api and disk_attributes_api["type"] == "text":
                        attributes_text = disk_attributes_api["text"].split("\n")
                        for value_text in attributes_text:
                            value_json = value_text.split(":")
                            if len(value_json) >= 2:
                                attributes_json.append(
                                    {
                                        "name": value_json[0].strip(),
                                        "raw": value_json[1].strip(),
                                    }
                                )

                for disk_attribute in attributes_json:
                    if disk_attribute["name"] in ("Power_Cycle_Count", "Power Cycles"):
                        disk_attributes["Power_Cycle_Count"]=disk_attribute["raw"]
                    elif disk_attribute["name"] in ("Temperature_Celsius", "Temperature"):
                        disk_attributes["Temperature_Celsius"]=disk_attribute["raw"].split(" ", 1)[0]

                return ProxmoxDiskData(
                    type=ProxmoxType.Disk,
                    node=self.node_name,
                    path=self.resource_id,
                    size=disk["size"] if "size" in disk else None,
                    health=disk["health"] if "health" in disk else None,
                    vendor=disk["vendor"] if "vendor" in disk else None,
                    serial=disk["serial"] if "serial" in disk else None,
                    model=disk["model"] if "model" in disk else None,
                    disk_rpm=disk["rpm"] if "rpm" in disk else None,
                    disk_type=disk["type"] if "type" in disk else None,
                    temperature=disk_attributes["Temperature_Celsius"] if "Temperature_Celsius" in disk_attributes else None,
                    power_cycles=disk_attributes["Power_Cycle_Count"] if "Power_Cycle_Count" in disk_attributes else None,
                )

        raise UpdateFailed(f"Disk {self.resource_id} not found on node {self.node_name}.")


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
                f"{self.config_entry.entry_id}_{api_category.upper()}_{self.resource_id}",
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
            self.resource_id,
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
                permission_check = "['perm','/nodes/{resource}',['Sys.Audit']]"

    if resource_type == ProxmoxType.QEMU:
        try:
            self.proxmox.nodes(resource_node).qemu(resource).status.current.get()
        except ResourceException as error:
            if error.status_code == 403:
                permissions = True
                permission_check = "['perm','/vms/{resource}',['VM.Audit']]"

    if resource_type == ProxmoxType.LXC:
        try:
            self.proxmox.nodes(resource_node).lxc(resource).status.current.get()
        except ResourceException as error:
            if error.status_code == 403:
                permissions = True
                permission_check = "['perm','/vms/{resource}',['VM.Audit']]"

    if resource_type == ProxmoxType.Storage:
        try:
            self.proxmox.nodes(resource_node).storage(resource).get()
        except ResourceException as error:
            if error.status_code == 403:
                permissions = True
                permission_check = f"['perm','/storage/{resource}',['Datastore.Audit'],'any',1]"

    if resource_type == ProxmoxType.Update:
        try:
            self.proxmox.nodes(resource_node).apt.update.get()
        except ResourceException as error:
            if error.status_code == 403:
                permissions = True
                permission_check = f"['perm','/nodes/{resource_node}',['Sys.Modify']]"

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
                "permission": permission_check,
            },
        )
    return permissions
