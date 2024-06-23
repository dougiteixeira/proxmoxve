"""Config Flow for ProxmoxVE."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import proxmoxer
from requests.exceptions import ConnectTimeout, SSLError
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import (
    CONF_BASE,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import device_registry as dr, issue_registry as ir, selector
import homeassistant.helpers.config_validation as cv

from .api import ProxmoxClient, get_api
from .const import (
    CONF_CONTAINERS,
    CONF_DISKS_ENABLE,
    CONF_LXC,
    CONF_NODE,
    CONF_NODES,
    CONF_QEMU,
    CONF_REALM,
    CONF_STORAGE,
    CONF_VMS,
    COORDINATORS,
    DEFAULT_PORT,
    DEFAULT_REALM,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    INTEGRATION_TITLE,
    LOGGER,
    VERSION_REMOVE_YAML,
    ProxmoxType,
)

SCHEMA_HOST_BASE: vol.Schema = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
    }
)
SCHEMA_HOST_SSL: vol.Schema = vol.Schema(
    {
        vol.Required(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): bool,
    }
)
SCHEMA_HOST_AUTH: vol.Schema = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_REALM, default=DEFAULT_REALM): str,
    }
)
SCHEMA_HOST_FULL: vol.Schema = SCHEMA_HOST_BASE.extend(SCHEMA_HOST_SSL.schema).extend(
    SCHEMA_HOST_AUTH.schema
)


class ProxmoxOptionsFlowHandler(config_entries.OptionsFlow):
    """Config flow options for ProxmoxVE."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize ProxmoxVE options flow."""
        self.config_entry: config_entries.ConfigEntry = config_entry
        self._proxmox_client: ProxmoxClient
        self._nodes: dict[str, Any] = {}
        self._host: str | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the Proxmox VE options."""
        return await self.async_step_menu(user_input)

    async def async_step_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the Proxmox VE options - Menu."""
        return self.async_show_menu(
            step_id="menu",
            menu_options=[
                "host_auth",
                "change_expose",
            ],
        )

    async def async_step_host_auth(self, user_input: dict[str, Any]) -> FlowResult:
        """Manage the host options step for proxmoxve config flow."""
        errors = {}

        if user_input is not None:
            host: str = str(self.config_entry.data[CONF_HOST])
            port: int = int(str(self.config_entry.data[CONF_PORT]))
            user: str = str(user_input.get(CONF_USERNAME))
            realm: str = str(user_input.get(CONF_REALM))
            password: str = str(user_input.get(CONF_PASSWORD))
            verify_ssl = user_input.get(CONF_VERIFY_SSL)

            try:
                self._proxmox_client = ProxmoxClient(
                    host=host,
                    port=port,
                    user=user,
                    realm=realm,
                    password=password,
                    verify_ssl=verify_ssl,
                )

                await self.hass.async_add_executor_job(
                    self._proxmox_client.build_client
                )

            except proxmoxer.AuthenticationError:
                errors[CONF_USERNAME] = "auth_error"
            except SSLError:
                errors[CONF_VERIFY_SSL] = "ssl_rejection"
            except ConnectTimeout:
                errors[CONF_HOST] = "cant_connect"
            except Exception:  # pylint: disable=broad-except
                errors[CONF_BASE] = "general_error"

            else:
                config_data: dict[str, Any] = (
                    self.config_entry.data.copy()
                    if self.config_entry.data is not None
                    else {}
                )
                config_data[CONF_USERNAME] = user_input.get(CONF_USERNAME)
                config_data[CONF_PASSWORD] = user_input.get(CONF_PASSWORD)
                config_data[CONF_REALM] = user_input.get(CONF_REALM)
                config_data[CONF_VERIFY_SSL] = user_input.get(CONF_VERIFY_SSL)

                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data=config_data,
                )

                return self.async_abort(reason="changes_successful")

        return self.async_show_form(
            step_id="host_auth",
            data_schema=self.add_suggested_values_to_schema(
                (SCHEMA_HOST_AUTH.extend(SCHEMA_HOST_SSL.schema)),
                self.config_entry.data or user_input,
            ),
            errors=errors,
        )

    async def async_step_change_expose(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle the Node/QEMU/LXC selection step."""

        if user_input is None:
            old_nodes = []
            resource_nodes = []

            for node in self.config_entry.data[CONF_NODES]:
                old_nodes.append(node)
                resource_nodes.append(node)

            old_qemu = []

            for qemu in self.config_entry.data[CONF_QEMU]:
                old_qemu.append(str(qemu))

            old_lxc = []

            for lxc in self.config_entry.data[CONF_LXC]:
                old_lxc.append(str(lxc))

            old_storage = []

            for storage in self.config_entry.data[CONF_STORAGE]:
                old_storage.append(str(storage))

            host = self.config_entry.data[CONF_HOST]
            port = self.config_entry.data[CONF_PORT]
            user = self.config_entry.data[CONF_USERNAME]
            realm = self.config_entry.data[CONF_REALM]
            password = self.config_entry.data[CONF_PASSWORD]
            verify_ssl = self.config_entry.data[CONF_VERIFY_SSL]

            try:
                self._proxmox_client = ProxmoxClient(
                    host=host,
                    port=port,
                    user=user,
                    realm=realm,
                    password=password,
                    verify_ssl=verify_ssl,
                )

                await self.hass.async_add_executor_job(
                    self._proxmox_client.build_client
                )
            except proxmoxer.backends.https.AuthenticationError:
                return self.async_abort(reason="auth_error")
            except SSLError:
                return self.async_abort(reason="ssl_rejection")
            except ConnectTimeout:
                return self.async_abort(reason="cant_connect")
            except Exception:  # pylint: disable=broad-except
                return self.async_abort(reason="general_error")

            proxmox = self._proxmox_client.get_api_client()

            resources = await self.hass.async_add_executor_job(
                get_api, proxmox, "cluster/resources"
            )

            resource_qemu = {}
            resource_lxc = {}
            resource_storage = {}
            resource: dict[str, Any]
            for resource in resources if resources is not None else []:
                if ("type" in resource) and (resource["type"] == ProxmoxType.Node):
                    if resource["node"] not in resource_nodes:
                        resource_nodes.append(resource["node"])
                if ("type" in resource) and (resource["type"] == ProxmoxType.QEMU):
                    if "name" in resource:
                        resource_qemu[str(resource["vmid"])] = (
                            f"{resource['vmid']} {resource['name']}"
                        )
                    else:
                        resource_qemu[str(resource["vmid"])] = f"{resource['vmid']}"
                if ("type" in resource) and (resource["type"] == ProxmoxType.LXC):
                    if "name" in resource:
                        resource_lxc[str(resource["vmid"])] = (
                            f"{resource['vmid']} {resource['name']}"
                        )
                    else:
                        resource_lxc[str(resource["vmid"])] = f"{resource['vmid']}"
                if ("type" in resource) and (resource["type"] == ProxmoxType.Storage):
                    if "storage" in resource:
                        resource_storage[str(resource["id"])] = resource["id"]

            return self.async_show_form(
                step_id="change_expose",
                data_schema=vol.Schema(
                    {
                        vol.Optional(CONF_NODES, default=old_nodes): cv.multi_select(
                            resource_nodes,
                        ),
                        vol.Optional(CONF_QEMU, default=old_qemu): cv.multi_select(
                            {
                                **dict.fromkeys(old_qemu),
                                **resource_qemu,
                            }
                        ),
                        vol.Optional(CONF_LXC, default=old_lxc): cv.multi_select(
                            {
                                **dict.fromkeys(old_lxc),
                                **resource_lxc,
                            }
                        ),
                        vol.Optional(
                            CONF_STORAGE, default=old_storage
                        ): cv.multi_select(
                            {
                                **dict.fromkeys(old_storage),
                                **resource_storage,
                            }
                        ),
                        vol.Optional(
                            CONF_DISKS_ENABLE,
                            default=self.config_entry.options.get(
                                CONF_DISKS_ENABLE, True
                            ),
                        ): selector.BooleanSelector(),
                    }
                ),
            )

        config_data: dict[str, Any] = (
            self.config_entry.data.copy() if self.config_entry.data is not None else {}
        )

        new_selection = await self.async_process_selection_changes(user_input)

        config_data.update(
            {
                CONF_NODES: new_selection[CONF_NODES],
                CONF_QEMU: new_selection[CONF_QEMU],
                CONF_LXC: new_selection[CONF_LXC],
                CONF_STORAGE: new_selection[CONF_STORAGE],
            }
        )

        options_data = {CONF_DISKS_ENABLE: user_input.get(CONF_DISKS_ENABLE)}

        self.hass.config_entries.async_update_entry(
            self.config_entry, data=config_data, options=options_data
        )

        await self.hass.config_entries.async_reload(self.config_entry.entry_id)

        return self.async_abort(reason="changes_successful")

    async def async_remove_device(
        self,
        entry_id: str,
        device_identifier: str,
    ) -> bool:
        """Remove device."""
        device_identifiers = {(DOMAIN, device_identifier)}
        dev_reg = dr.async_get(self.hass)
        device = dev_reg.async_get_or_create(
            config_entry_id=entry_id,
            identifiers=device_identifiers,
        )

        dev_reg.async_update_device(
            device_id=device.id,
            remove_config_entry_id=entry_id,
        )
        LOGGER.debug("Device %s (%s) removed", device.name, device.id)
        return True

    async def async_process_selection_changes(
        self,
        user_input: dict[str, Any],
    ) -> dict[str, Any]:
        """Process resource selection changes."""

        node_selecition = []
        if (
            CONF_NODES in user_input
            and (node_user := user_input.get(CONF_NODES)) is not None
        ):
            for node in node_user:
                node_selecition.append(node)

        for node in self.config_entry.data[CONF_NODES]:
            if node not in node_selecition:
                # Remove device disks
                coordinators = self.hass.data[DOMAIN][self.config_entry.entry_id][
                    COORDINATORS
                ]

                # Remove device node
                identifier = (
                    f"{self.config_entry.entry_id}_{ProxmoxType.Node.upper()}_{node}"
                )
                await self.async_remove_device(
                    entry_id=self.config_entry.entry_id,
                    device_identifier=identifier,
                )
                ir.async_delete_issue(
                    self.hass,
                    DOMAIN,
                    f"{self.config_entry.entry_id}_{node}_resource_nonexistent",
                )

            if node not in (
                node_selecition if node_selecition is not None else []
            ) or not user_input.get(CONF_DISKS_ENABLE):
                coordinators = self.hass.data[DOMAIN][self.config_entry.entry_id][
                    COORDINATORS
                ]
                if f"{ProxmoxType.Disk}_{node}" in coordinators:
                    for coordinator_disk in coordinators[f"{ProxmoxType.Disk}_{node}"]:
                        if (coordinator_data := coordinator_disk.data) is None:
                            continue

                        identifier = f"{self.config_entry.entry_id}_{ProxmoxType.Disk.upper()}_{node}_{coordinator_data.path}"
                        await self.async_remove_device(
                            entry_id=self.config_entry.entry_id,
                            device_identifier=identifier,
                        )

        qemu_selecition = []
        if (
            CONF_QEMU in user_input
            and (qemu_user := user_input.get(CONF_QEMU)) is not None
        ):
            for qemu in qemu_user:
                qemu_selecition.append(qemu)

        for qemu_id in self.config_entry.data[CONF_QEMU]:
            if qemu_id not in qemu_selecition:
                # Remove device
                identifier = (
                    f"{self.config_entry.entry_id}_{ProxmoxType.QEMU.upper()}_{qemu_id}"
                )
                await self.async_remove_device(
                    entry_id=self.config_entry.entry_id,
                    device_identifier=identifier,
                )
                ir.async_delete_issue(
                    self.hass,
                    DOMAIN,
                    f"{self.config_entry.entry_id}_{qemu_id}_resource_nonexistent",
                )

        lxc_selecition = []
        if (
            CONF_LXC in user_input
            and (lxc_user := user_input.get(CONF_LXC)) is not None
        ):
            for lxc in lxc_user:
                lxc_selecition.append(lxc)

        for lxc_id in self.config_entry.data[CONF_LXC]:
            if lxc_id not in lxc_selecition:
                # Remove device
                identifier = (
                    f"{self.config_entry.entry_id}_{ProxmoxType.LXC.upper()}_{lxc_id}"
                )
                await self.async_remove_device(
                    entry_id=self.config_entry.entry_id,
                    device_identifier=identifier,
                )
                ir.async_delete_issue(
                    self.hass,
                    DOMAIN,
                    f"{self.config_entry.entry_id}_{lxc_id}_resource_nonexistent",
                )

        storage_selecition = []
        if (
            CONF_STORAGE in user_input
            and (storage_user := user_input.get(CONF_STORAGE)) is not None
        ):
            for storage in storage_user:
                storage_selecition.append(storage)

        for storage_id in self.config_entry.data[CONF_STORAGE]:
            if storage_id not in storage_selecition:
                # Remove device
                identifier = f"{self.config_entry.entry_id}_{ProxmoxType.Storage.upper()}_{storage_id}"
                await self.async_remove_device(
                    entry_id=self.config_entry.entry_id,
                    device_identifier=identifier,
                )
                ir.async_delete_issue(
                    self.hass,
                    DOMAIN,
                    f"{self.config_entry.entry_id}_{storage_id}_resource_nonexistent",
                )

        return {
            CONF_NODES: node_selecition,
            CONF_QEMU: qemu_selecition,
            CONF_LXC: lxc_selecition,
            CONF_STORAGE: storage_selecition,
        }


class ProxmoxVEConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """ProxmoxVE Config Flow class."""

    VERSION = 5
    _reauth_entry: config_entries.ConfigEntry | None = None

    def __init__(self) -> None:
        """Init for ProxmoxVE config flow."""
        super().__init__()

        self._config: dict[str, Any] = {}
        self._nodes: dict[str, Any] = {}
        self._host: str
        self._proxmox_client: ProxmoxClient | None = None

    async def async_step_import(self, import_config: dict[str, Any]) -> FlowResult:
        """Import existing configuration."""

        errors = {}

        if f"{import_config.get(CONF_HOST)}_{import_config.get(CONF_PORT)}" in [
            f"{entry.data.get(CONF_HOST)}_{entry.data.get(CONF_PORT)}"
            for entry in self._async_current_entries()
        ]:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"{import_config.get(CONF_HOST)}_{import_config.get(CONF_PORT)}_import_already_configured",
                breaks_in_ha_version=VERSION_REMOVE_YAML,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="import_already_configured",
                translation_placeholders={
                    "integration": INTEGRATION_TITLE,
                    "platform": DOMAIN,
                    "host": str(import_config.get(CONF_HOST)),
                    "port": str(import_config.get(CONF_PORT)),
                },
            )
            return self.async_abort(reason="import_failed")

        host: str = str(import_config.get(CONF_HOST))
        port: int = int(str(import_config.get(CONF_PORT)))
        user: str = str(import_config.get(CONF_USERNAME))
        realm: str = str(import_config.get(CONF_REALM))
        password: str = str(import_config.get(CONF_PASSWORD))
        verify_ssl = import_config.get(CONF_VERIFY_SSL)

        proxmox_client = ProxmoxClient(
            host=host,
            port=port,
            user=user,
            realm=realm,
            password=password,
            verify_ssl=verify_ssl,
        )

        try:
            await self.hass.async_add_executor_job(proxmox_client.build_client)
        except proxmoxer.backends.https.AuthenticationError:
            errors[CONF_USERNAME] = "auth_error"
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"{import_config.get(CONF_HOST)}_{import_config.get(CONF_PORT)}_import_auth_error",
                breaks_in_ha_version=VERSION_REMOVE_YAML,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="import_auth_error",
                translation_placeholders={
                    "integration": INTEGRATION_TITLE,
                    "platform": DOMAIN,
                    "host": str(import_config.get(CONF_HOST)),
                    "port": str(import_config.get(CONF_PORT)),
                },
            )
        except SSLError:
            errors[CONF_VERIFY_SSL] = "ssl_rejection"
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"{import_config.get(CONF_HOST)}_{import_config.get(CONF_PORT)}_import_ssl_rejection",
                breaks_in_ha_version=VERSION_REMOVE_YAML,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="import_ssl_rejection",
                translation_placeholders={
                    "integration": INTEGRATION_TITLE,
                    "platform": DOMAIN,
                    "host": str(import_config.get(CONF_HOST)),
                    "port": str(import_config.get(CONF_PORT)),
                },
            )
        except ConnectTimeout:
            errors[CONF_HOST] = "cant_connect"
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"{import_config.get(CONF_HOST)}_{import_config.get(CONF_PORT)}_import_cant_connect",
                breaks_in_ha_version=VERSION_REMOVE_YAML,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="import_cant_connect",
                translation_placeholders={
                    "integration": INTEGRATION_TITLE,
                    "platform": DOMAIN,
                    "host": str(import_config.get(CONF_HOST)),
                    "port": str(import_config.get(CONF_PORT)),
                },
            )
        except Exception:  # pylint: disable=broad-except
            errors[CONF_BASE] = "general_error"
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"{import_config.get(CONF_HOST)}_{import_config.get(CONF_PORT)}_import_general_error",
                breaks_in_ha_version=VERSION_REMOVE_YAML,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="import_general_error",
                translation_placeholders={
                    "integration": INTEGRATION_TITLE,
                    "platform": DOMAIN,
                    "host": str(import_config.get(CONF_HOST)),
                    "port": str(import_config.get(CONF_PORT)),
                },
            )

        if errors:
            return self.async_abort(reason="import_failed")

        proxmox_nodes_host = []
        if proxmox := (proxmox_client.get_api_client()):
            proxmox_nodes = await self.hass.async_add_executor_job(
                get_api, proxmox, "nodes"
            )

            for node in proxmox_nodes if proxmox_nodes is not None else []:
                proxmox_nodes_host.append(node[CONF_NODE])

        if (
            import_config is not None
            and CONF_NODES in import_config
            and (import_nodes := import_config.get(CONF_NODES)) is not None
        ):
            import_config[CONF_NODES] = []
            for node_data in import_nodes:
                node = node_data[CONF_NODE]
                if node in proxmox_nodes_host:
                    import_config[CONF_NODES].append(node)
                    import_config[CONF_QEMU] = node_data[CONF_VMS]
                    import_config[CONF_LXC] = node_data[CONF_CONTAINERS]
                else:
                    ir.async_create_issue(
                        self.hass,
                        DOMAIN,
                        f"{import_config.get(CONF_HOST)}_{import_config.get(CONF_PORT)}_{import_config.get(CONF_NODE)}_import_node_not_exist",
                        breaks_in_ha_version=VERSION_REMOVE_YAML,
                        is_fixable=False,
                        severity=ir.IssueSeverity.WARNING,
                        translation_key="import_node_not_exist",
                        translation_placeholders={
                            "integration": INTEGRATION_TITLE,
                            "platform": DOMAIN,
                            "host": str(import_config.get(CONF_HOST)),
                            "port": str(import_config.get(CONF_PORT)),
                            "node": str(node),
                        },
                    )

        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"{import_config.get(CONF_HOST)}_{import_config.get(CONF_PORT)}_import_success",
            breaks_in_ha_version=VERSION_REMOVE_YAML,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="import_success",
            translation_placeholders={
                "integration": INTEGRATION_TITLE,
                "platform": DOMAIN,
                "host": str(import_config.get(CONF_HOST)),
                "port": str(import_config.get(CONF_PORT)),
            },
        )

        return self.async_create_entry(
            title=(f"{import_config.get(CONF_HOST)}:{import_config.get(CONF_PORT)}"),
            data=import_config,
        )

    async def async_step_reauth(self, data: Mapping[str, Any]) -> FlowResult:
        """Handle a reauthorization flow request."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm reauth dialog."""
        errors = {}
        assert self._reauth_entry
        if user_input is not None:
            host: str = str(self._reauth_entry.data[CONF_HOST])
            port: int = int(str(self._reauth_entry.data[CONF_PORT]))
            verify_ssl: bool = bool(self._reauth_entry.data[CONF_VERIFY_SSL])
            user: str = str(user_input.get(CONF_USERNAME))
            realm: str = str(user_input.get(CONF_REALM))
            password: str = str(user_input.get(CONF_PASSWORD))

            try:
                self._proxmox_client = ProxmoxClient(
                    host,
                    port=port,
                    user=user,
                    realm=realm,
                    password=password,
                    verify_ssl=verify_ssl,
                )

                await self.hass.async_add_executor_job(
                    self._proxmox_client.build_client
                )

            except proxmoxer.backends.https.AuthenticationError:
                errors[CONF_USERNAME] = "auth_error"
            except SSLError:
                errors[CONF_BASE] = "ssl_rejection"
            except ConnectTimeout:
                errors[CONF_BASE] = "cant_connect"
            except Exception:  # pylint: disable=broad-except
                errors[CONF_BASE] = "general_error"

            else:
                config_data: dict[str, Any] = (
                    self._reauth_entry.data.copy()
                    if self._reauth_entry.data is not None
                    else {}
                )
                config_data.update(
                    {
                        CONF_USERNAME: user_input.get(CONF_USERNAME),
                        CONF_PASSWORD: user_input.get(CONF_PASSWORD),
                        CONF_REALM: user_input.get(CONF_REALM),
                    }
                )
                self.hass.config_entries.async_update_entry(
                    self._reauth_entry, data=config_data
                )
                await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                SCHEMA_HOST_AUTH, user_input or self._reauth_entry.data
            ),
            errors=errors,
        )

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Manual user configuration."""
        return await self.async_step_init(user_input)

    async def async_step_init(self, user_input) -> FlowResult:
        """Async step user for proxmoxve config flow."""
        return await self.async_step_host(user_input)

    async def async_step_host(self, user_input) -> FlowResult:
        """Async step of host config flow for proxmoxve."""
        errors = {}

        if user_input:
            if (
                f"{user_input.get(CONF_HOST)}_{user_input.get(CONF_PORT, DEFAULT_PORT)}"
                in [
                    f"{entry.data.get(CONF_HOST)}_{entry.data.get(CONF_PORT)}"
                    for entry in self._async_current_entries()
                ]
            ):
                return self.async_abort(reason="already_configured")

            host = user_input.get(CONF_HOST, "")
            port = user_input.get(CONF_PORT, DEFAULT_PORT)
            username = user_input.get(CONF_USERNAME, "")
            password = user_input.get(CONF_PASSWORD, "")
            realm = user_input.get(CONF_REALM, DEFAULT_REALM)
            verify_ssl = user_input.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)

            self._host = host

            if port > 65535 or port <= 0:
                errors[CONF_PORT] = "invalid_port"

            if not errors:
                try:
                    self._proxmox_client = ProxmoxClient(
                        host,
                        port=port,
                        user=username,
                        realm=realm,
                        password=password,
                        verify_ssl=verify_ssl,
                    )

                    await self.hass.async_add_executor_job(
                        self._proxmox_client.build_client
                    )

                except proxmoxer.backends.https.AuthenticationError:
                    errors[CONF_USERNAME] = "auth_error"
                except SSLError:
                    errors[CONF_VERIFY_SSL] = "ssl_rejection"
                except ConnectTimeout:
                    errors[CONF_HOST] = "cant_connect"
                except Exception:  # pylint: disable=broad-except
                    errors[CONF_BASE] = "general_error"

                else:
                    self._config[CONF_HOST] = host
                    self._config[CONF_PORT] = port
                    self._config[CONF_USERNAME] = username
                    self._config[CONF_PASSWORD] = password
                    self._config[CONF_REALM] = realm
                    self._config[CONF_VERIFY_SSL] = verify_ssl

                    return await self.async_step_expose()

        return self.async_show_form(
            step_id="host",
            data_schema=self.add_suggested_values_to_schema(
                SCHEMA_HOST_FULL, user_input
            ),
            errors=errors,
        )

    async def async_step_expose(
        self,
        user_input: dict[str, Any] | None = None,
        node: str | None = None,
    ) -> FlowResult:
        """Handle the Node/QEMU/LXC selection step."""

        if user_input is None:
            if (proxmox_cliente := self._proxmox_client) is not None:
                proxmox = proxmox_cliente.get_api_client()

            resources = await self.hass.async_add_executor_job(
                get_api, proxmox, "cluster/resources"
            )

            resource_nodes = []
            resource_qemu = {}
            resource_lxc = {}
            resource_storage = {}
            if resources is None:
                return self.async_abort(reason="no_resources")
            for resource in resources:
                if ("type" in resource) and (resource["type"] == ProxmoxType.Node):
                    if resource["node"] not in resource_nodes:
                        resource_nodes.append(resource["node"])
                if ("type" in resource) and (resource["type"] == ProxmoxType.QEMU):
                    if "name" in resource:
                        resource_qemu[str(resource["vmid"])] = (
                            f"{resource['vmid']} {resource['name']}"
                        )
                    else:
                        resource_qemu[str(resource["vmid"])] = f"{resource['vmid']}"
                if ("type" in resource) and (resource["type"] == ProxmoxType.LXC):
                    if "name" in resource:
                        resource_lxc[str(resource["vmid"])] = (
                            f"{resource['vmid']} {resource['name']}"
                        )
                    else:
                        resource_lxc[str(resource["vmid"])] = f"{resource['vmid']}"
                if ("type" in resource) and (resource["type"] == ProxmoxType.Storage):
                    if "storage" in resource:
                        resource_storage[str(resource["storage"])] = (
                            f"{resource['storage']} {resource['id']}"
                        )
                    else:
                        resource_lxc[str(resource["storage"])] = (
                            f"{resource['storage']}"
                        )

            return self.async_show_form(
                step_id="expose",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_NODES): cv.multi_select(resource_nodes),
                        vol.Optional(CONF_QEMU): cv.multi_select(resource_qemu),
                        vol.Optional(CONF_LXC): cv.multi_select(resource_lxc),
                        vol.Optional(CONF_STORAGE): cv.multi_select(resource_storage),
                        vol.Optional(
                            CONF_DISKS_ENABLE,
                            default=True,
                        ): selector.BooleanSelector(),
                    }
                ),
            )

        if CONF_NODES not in self._config:
            self._config[CONF_NODES] = []
        if (
            CONF_NODES in user_input
            and (node_user := user_input.get(CONF_NODES)) is not None
        ):
            for node_selection in node_user:
                self._config[CONF_NODES].append(node_selection)

        if CONF_QEMU not in self._config:
            self._config[CONF_QEMU] = []
        if (
            CONF_QEMU in user_input
            and (qemu_user := user_input.get(CONF_QEMU)) is not None
        ):
            for qemu_selection in qemu_user:
                self._config[CONF_QEMU].append(qemu_selection)

        if CONF_LXC not in self._config:
            self._config[CONF_LXC] = []
        if (
            CONF_LXC in user_input
            and (lxc_user := user_input.get(CONF_LXC)) is not None
        ):
            for lxc_selection in lxc_user:
                self._config[CONF_LXC].append(lxc_selection)

        if CONF_STORAGE not in self._config:
            self._config[CONF_STORAGE] = []
        if (
            CONF_STORAGE in user_input
            and (storage_user := user_input.get(CONF_STORAGE)) is not None
        ):
            for storage_selection in storage_user:
                self._config[CONF_STORAGE].append(storage_selection)

        return self.async_create_entry(
            title=(f"{self._config[CONF_HOST]}:{self._config[CONF_PORT]}"),
            data=self._config,
            options={CONF_DISKS_ENABLE: user_input.get(CONF_DISKS_ENABLE)},
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Options callback for Proxmox."""
        return ProxmoxOptionsFlowHandler(config_entry)
