"""Support for Proxmox VE."""
from __future__ import annotations

from typing import Any
import warnings

from proxmoxer import AuthenticationError, ProxmoxAPI
from proxmoxer.core import ResourceException
from requests.exceptions import (
    ConnectionError as connError,
    ConnectTimeout,
    RetryError,
    SSLError,
)
from urllib3.exceptions import InsecureRequestWarning
import voluptuous as vol

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
)
from homeassistant.helpers.typing import ConfigType

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
    PROXMOX_CLIENT,
    VERSION_REMOVE_YAML,
    ProxmoxCommand,
    ProxmoxType,
)
from .coordinator import (
    ProxmoxDiskCoordinator,
    ProxmoxLXCCoordinator,
    ProxmoxNodeCoordinator,
    ProxmoxQEMUCoordinator,
    ProxmoxStorageCoordinator,
    ProxmoxUpdateCoordinator,
)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
]

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.All(
            cv.ensure_list,
            [
                vol.Schema(
                    {
                        vol.Required(CONF_HOST): cv.string,
                        vol.Required(CONF_USERNAME): cv.string,
                        vol.Required(CONF_PASSWORD): cv.string,
                        vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
                        vol.Optional(CONF_REALM, default=DEFAULT_REALM): cv.string,
                        vol.Optional(
                            CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL
                        ): cv.boolean,
                        vol.Required(CONF_NODES): vol.All(
                            cv.ensure_list,
                            [
                                vol.Schema(
                                    {
                                        vol.Required(CONF_NODE): cv.string,
                                        vol.Optional(CONF_VMS, default=[]): [
                                            cv.positive_int
                                        ],
                                        vol.Optional(CONF_CONTAINERS, default=[]): [
                                            cv.positive_int
                                        ],
                                    }
                                )
                            ],
                        ),
                    }
                )
            ],
        )
    },
    extra=vol.ALLOW_EXTRA,
)

warnings.filterwarnings("ignore", category=InsecureRequestWarning)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the platform."""

    # import to config flow
    if DOMAIN in config:
        LOGGER.warning(
            # Proxmox VE config flow added and should be removed.
            "Configuration of the Proxmox in YAML is deprecated and should "
            "be removed in %s. Resolve the import issues and remove the "
            "YAML configuration from your configuration.yaml file",
            VERSION_REMOVE_YAML,
        )
        async_create_issue(
            hass,
            DOMAIN,
            "yaml_deprecated",
            breaks_in_ha_version=VERSION_REMOVE_YAML,
            is_fixable=False,
            severity=IssueSeverity.WARNING,
            translation_key="yaml_deprecated",
            translation_placeholders={
                "integration": INTEGRATION_TITLE,
                "platform": DOMAIN,
                "version": VERSION_REMOVE_YAML,
            },
        )
        for conf in config[DOMAIN]:
            if conf.get(CONF_PORT) > 65535 or conf.get(CONF_PORT) <= 0:
                async_create_issue(
                    hass,
                    DOMAIN,
                    f"{conf.get[CONF_HOST]}_{conf.get[CONF_PORT]}_import_invalid_port",
                    is_fixable=False,
                    severity=IssueSeverity.ERROR,
                    translation_key="import_invalid_port",
                    translation_placeholders={
                        "integration": INTEGRATION_TITLE,
                        "platform": DOMAIN,
                        "host": conf.get[CONF_HOST],
                        "port": conf.get[CONF_PORT],
                    },
                )
            else:
                hass.async_create_task(
                    hass.config_entries.flow.async_init(
                        DOMAIN,
                        context={"source": SOURCE_IMPORT},
                        data=conf,
                    )
                )
    return True


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Migrate old entry."""
    LOGGER.debug("Migrating from version %s", config_entry.version)

    if config_entry.version == 1:
        device_identifiers = []
        device_identifiers.append(
            f"{config_entry.data[CONF_HOST]}_{config_entry.data[CONF_PORT]}"
        )
        device_identifiers.append(
            f"{config_entry.data[CONF_HOST]}_{config_entry.data[CONF_PORT]}_{config_entry.data.get(CONF_NODE)}"
        )
        for resource in config_entry.data[CONF_QEMU]:
            device_identifiers.append(
                f"{config_entry.data[CONF_HOST]}_{config_entry.data[CONF_PORT]}_{config_entry.data.get(CONF_NODE)}_{resource}"
            )
        for resource in config_entry.data[CONF_LXC]:
            device_identifiers.append(
                f"{config_entry.data[CONF_HOST]}_{config_entry.data[CONF_PORT]}_{config_entry.data.get(CONF_NODE)}_{resource}"
            )

        node = []
        node.append(config_entry.data.get(CONF_NODE))
        data_new = {
            CONF_HOST: config_entry.data.get(CONF_HOST),
            CONF_PORT: config_entry.data.get(CONF_PORT),
            CONF_USERNAME: config_entry.data.get(CONF_USERNAME),
            CONF_PASSWORD: config_entry.data.get(CONF_PASSWORD),
            CONF_REALM: config_entry.data.get(CONF_REALM),
            CONF_VERIFY_SSL: config_entry.data.get(CONF_VERIFY_SSL),
            CONF_NODES: node,
            CONF_QEMU: config_entry.data.get(CONF_QEMU),
            CONF_LXC: config_entry.data.get(CONF_LXC),
        }

        config_entry.version = 2
        hass.config_entries.async_update_entry(config_entry, data=data_new, options={})

        LOGGER.debug("Migration - remove devices: %s", device_identifiers)
        for device_identifier in device_identifiers:
            device_identifiers = {
                (
                    DOMAIN,
                    device_identifier,
                )
            }
            dev_reg = dr.async_get(hass)
            device = dev_reg.async_get_or_create(
                config_entry_id=config_entry.entry_id,
                identifiers=device_identifiers,
            )

            dev_reg.async_update_device(
                device_id=device.id,
                remove_config_entry_id=config_entry.entry_id,
            )

    if config_entry.version == 2:
        device_identifiers = []
        for resource in config_entry.data.get(CONF_NODES):
            device_identifiers.append(f"{ProxmoxType.Node.upper()}_{resource}")
        for resource in config_entry.data.get(CONF_QEMU):
            device_identifiers.append(f"{ProxmoxType.QEMU.upper()}_{resource}")
        for resource in config_entry.data.get(CONF_LXC):
            device_identifiers.append(f"{ProxmoxType.LXC.upper()}_{resource}")

        config_entry.version = 3
        hass.config_entries.async_update_entry(
            config_entry, data=config_entry.data, options={}
        )

        LOGGER.debug("Migration - remove devices: %s", device_identifiers)
        for device_identifier in device_identifiers:
            device_identifiers = {
                (
                    DOMAIN,
                    device_identifier,
                )
            }
            dev_reg = dr.async_get(hass)
            device = dev_reg.async_get_or_create(
                config_entry_id=config_entry.entry_id,
                identifiers=device_identifiers,
            )

            dev_reg.async_update_device(
                device_id=device.id,
                remove_config_entry_id=config_entry.entry_id,
            )


    if config_entry.version == 3:
        config_entry.version = 4
        data_new = {
            CONF_HOST: config_entry.data.get(CONF_HOST),
            CONF_PORT: config_entry.data.get(CONF_PORT),
            CONF_USERNAME: config_entry.data.get(CONF_USERNAME),
            CONF_PASSWORD: config_entry.data.get(CONF_PASSWORD),
            CONF_REALM: config_entry.data.get(CONF_REALM),
            CONF_VERIFY_SSL: config_entry.data.get(CONF_VERIFY_SSL),
            CONF_NODES: config_entry.data.get(CONF_NODES),
            CONF_QEMU: config_entry.data.get(CONF_QEMU),
            CONF_LXC: config_entry.data.get(CONF_LXC),
            CONF_STORAGE: [],
        }
        hass.config_entries.async_update_entry(
            config_entry, data=data_new, options={}
        )

    LOGGER.info("Migration to version %s successful", config_entry.version)

    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up the platform."""

    hass.data.setdefault(DOMAIN, {})
    entry_data = config_entry.data

    host = entry_data[CONF_HOST]
    port = entry_data[CONF_PORT]
    user = entry_data[CONF_USERNAME]
    realm = entry_data[CONF_REALM]
    password = entry_data[CONF_PASSWORD]
    verify_ssl = entry_data[CONF_VERIFY_SSL]

    # Construct an API client with the given data for the given host
    proxmox_client = ProxmoxClient(
        host=host,
        port=port,
        user=user,
        realm=realm,
        password=password,
        verify_ssl=verify_ssl,
    )
    try:
        await hass.async_add_executor_job(proxmox_client.build_client)
    except AuthenticationError as error:
        raise ConfigEntryAuthFailed from error
    except SSLError as error:
        raise ConfigEntryNotReady(
            "Unable to verify proxmox server SSL. Try using 'verify_ssl: false' "
            f"for proxmox instance {host}:{port}"
        ) from error
    except ConnectTimeout as error:
        raise ConfigEntryNotReady(
            f"Connection to host {host} timed out during setup"
        ) from error
    except RetryError as error:
        raise ConfigEntryNotReady(
            f"Connection is unreachable to host {host}"
        ) from error
    except connError as error:
        raise ConfigEntryNotReady(
            f"Connection is unreachable to host {host}"
        ) from error
    except ResourceException as error:
        raise ConfigEntryNotReady from error

    proxmox = await hass.async_add_executor_job(proxmox_client.get_api_client)

    coordinators: dict[
        str | int,
        ProxmoxNodeCoordinator | ProxmoxQEMUCoordinator | ProxmoxLXCCoordinator | ProxmoxStorageCoordinator | ProxmoxUpdateCoordinator | ProxmoxDiskCoordinator,
    ] = {}
    nodes_add_device = []

    resources = await hass.async_add_executor_job(proxmox.cluster.resources.get)
    LOGGER.debug("API Response - Resources: %s", resources)

    for node in config_entry.data[CONF_NODES]:
        if node in [
            node_proxmox["node"]
            for node_proxmox in await hass.async_add_executor_job(proxmox.nodes().get)
        ]:
            async_delete_issue(
                hass,
                DOMAIN,
                f"{config_entry.entry_id}_{node}_resource_nonexistent",
            )
            coordinator_node = ProxmoxNodeCoordinator(
                hass=hass,
                proxmox=proxmox,
                api_category=ProxmoxType.Node,
                node_name=node,
            )
            await coordinator_node.async_refresh()
            coordinators[node] = coordinator_node
            if coordinator_node.data is not None:
                nodes_add_device.append(node)


            coordinator_updates = ProxmoxUpdateCoordinator(
                hass=hass,
                proxmox=proxmox,
                api_category=ProxmoxType.Update,
                node_name=node,
            )
            await coordinator_updates.async_refresh()
            coordinators[f"{ProxmoxType.Update}_{node}"] = coordinator_updates

            if config_entry.options.get(CONF_DISKS_ENABLE, True):
                try:
                    disks = await hass.async_add_executor_job(proxmox.nodes(node).disks.list.get)
                except ResourceException as error:
                    continue

                coordinators[f"{node}_{ProxmoxType.Disk}"]=[]
                for disk in disks:
                    coordinator_disk = ProxmoxDiskCoordinator(
                        hass=hass,
                        proxmox=proxmox,
                        api_category=ProxmoxType.Disk,
                        node_name=node,
                        disk_id=disk["devpath"],
                    )
                    await coordinator_disk.async_refresh()
                    coordinators[f"{node}_{ProxmoxType.Disk}"].append(coordinator_disk)

        else:
            async_create_issue(
                hass,
                DOMAIN,
                f"{config_entry.entry_id}_{node}_resource_nonexistent",
                is_fixable=False,
                severity=IssueSeverity.ERROR,
                translation_key="resource_nonexistent",
                translation_placeholders={
                    "integration": INTEGRATION_TITLE,
                    "platform": DOMAIN,
                    "host": config_entry.data[CONF_HOST],
                    "port": config_entry.data[CONF_PORT],
                    "resource_type": ProxmoxType.Node.capitalize(),
                    "resource": node,
                    "permission": f"['perm','/nodes/{node}',['Sys.Audit']]",
                },
            )

    for vm_id in config_entry.data[CONF_QEMU]:
        if int(vm_id) in [
            (int(resource["vmid"]) if "vmid" in resource else None)
            for resource in resources
        ]:
            async_delete_issue(
                hass,
                DOMAIN,
                f"{config_entry.entry_id}_{vm_id}_resource_nonexistent",
            )
            coordinator_qemu = ProxmoxQEMUCoordinator(
                hass=hass,
                proxmox=proxmox,
                api_category=ProxmoxType.QEMU,
                qemu_id=vm_id,
            )
            await coordinator_qemu.async_refresh()
            coordinators[vm_id] = coordinator_qemu
        else:
            async_create_issue(
                hass,
                DOMAIN,
                f"{config_entry.entry_id}_{vm_id}_resource_nonexistent",
                is_fixable=False,
                severity=IssueSeverity.ERROR,
                translation_key="resource_nonexistent",
                translation_placeholders={
                    "integration": INTEGRATION_TITLE,
                    "platform": DOMAIN,
                    "host": config_entry.data[CONF_HOST],
                    "port": config_entry.data[CONF_PORT],
                    "resource_type": ProxmoxType.QEMU.upper(),
                    "resource": vm_id,
                    "permission":  f"['perm','/vms/{vm_id}',['VM.Audit']]",
                },
            )

    for container_id in config_entry.data[CONF_LXC]:
        if int(container_id) in [
            (int(resource["vmid"]) if "vmid" in resource else None)
            for resource in resources
        ]:
            async_delete_issue(
                hass,
                DOMAIN,
                f"{config_entry.entry_id}_{container_id}_resource_nonexistent",
            )
            coordinator_lxc = ProxmoxLXCCoordinator(
                hass=hass,
                proxmox=proxmox,
                api_category=ProxmoxType.LXC,
                container_id=container_id,
            )
            await coordinator_lxc.async_refresh()
            coordinators[container_id] = coordinator_lxc
        else:
            async_create_issue(
                hass,
                DOMAIN,
                f"{config_entry.entry_id}_{container_id}_resource_nonexistent",
                is_fixable=False,
                severity=IssueSeverity.ERROR,
                translation_key="resource_nonexistent",
                translation_placeholders={
                    "integration": INTEGRATION_TITLE,
                    "platform": DOMAIN,
                    "host": config_entry.data[CONF_HOST],
                    "port": config_entry.data[CONF_PORT],
                    "resource_type": ProxmoxType.LXC.upper(),
                    "resource": container_id,
                    "permission":  f"['perm','/vms/{container_id}',['VM.Audit']]",
                },
            )

    for storage_id in config_entry.data[CONF_STORAGE]:
        if storage_id in [
            (resource["storage"] if "storage" in resource else None)
            for resource in resources
        ]:
            async_delete_issue(
                hass,
                DOMAIN,
                f"{config_entry.entry_id}_{storage_id}_resource_nonexistent",
            )
            coordinator_storage = ProxmoxStorageCoordinator(
                hass=hass,
                proxmox=proxmox,
                api_category=ProxmoxType.Storage,
                storage_id=storage_id,
            )
            await coordinator_storage.async_refresh()
            coordinators[storage_id] = coordinator_storage
        else:
            async_create_issue(
                hass,
                DOMAIN,
                f"{config_entry.entry_id}_{storage_id}_resource_nonexistent",
                is_fixable=False,
                severity=IssueSeverity.ERROR,
                translation_key="resource_nonexistent",
                translation_placeholders={
                    "integration": INTEGRATION_TITLE,
                    "platform": DOMAIN,
                    "host": config_entry.data[CONF_HOST],
                    "port": config_entry.data[CONF_PORT],
                    "resource_type": ProxmoxType.Storage.capitalize(),
                    "resource": storage_id,
                    "permission":  f"['perm','/storage/{storage_id}',['Datastore.Audit'],'any',1]"
                },
            )

    hass.data[DOMAIN][config_entry.entry_id] = {
        PROXMOX_CLIENT: proxmox_client,
        COORDINATORS: coordinators,
    }

    for node in nodes_add_device:
        device_info(
            hass=hass,
            config_entry=config_entry,
            api_category=ProxmoxType.Node,
            node=node,
            create=True,
        )

    for platform in PLATFORMS:
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(config_entry, platform)
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Remove a config entry from a device."""
    dev_reg = dr.async_get(hass)
    dev_reg.async_update_device(
        device_id=device_entry.id,
        remove_config_entry_id=config_entry.entry_id,
    )
    LOGGER.debug("Device %s (%s) removed", device_entry.name, device_entry.id)
    return True


def device_info(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    api_category: ProxmoxType,
    node: str | None = None,
    resource_id: int | None = None,
    create: bool | None = False,
    cordinator_resource: dict[str,Any] | None = None,
):
    """Return the Device Info."""

    coordinators = hass.data[DOMAIN][config_entry.entry_id][COORDINATORS]

    host = config_entry.data[CONF_HOST]
    port = config_entry.data[CONF_PORT]

    proxmox_version = None
    manufacturer = None
    serial_number = None
    if api_category in (ProxmoxType.QEMU, ProxmoxType.LXC):
        coordinator = coordinators[resource_id]
        if (coordinator_data := coordinator.data) is not None:
            vm_name = coordinator_data.name
            node = coordinator_data.node

        name = f"{api_category.upper()} {vm_name} ({resource_id})"
        identifier = f"{config_entry.entry_id}_{api_category.upper()}_{resource_id}"
        url = f"https://{host}:{port}/#v1:0:={api_category}/{resource_id}"
        via_device = (
            DOMAIN,
            f"{config_entry.entry_id}_{ProxmoxType.Node.upper()}_{node}",
        )
        model = api_category.upper()

    elif api_category is ProxmoxType.Storage:
        coordinator = coordinators[resource_id]
        if (coordinator_data := coordinator.data) is not None:
            node = coordinator_data.node

        name = f"{api_category.capitalize()} {resource_id}"
        identifier = f"{config_entry.entry_id}_{api_category.upper()}_{resource_id}"
        url = f"https://{host}:{port}/#v1:0:={api_category}/{node}/{resource_id}"
        via_device = (
            DOMAIN,
            f"{config_entry.entry_id}_{ProxmoxType.Node.upper()}_{node}",
        )
        model = api_category.capitalize()

    elif api_category in (ProxmoxType.Node, ProxmoxType.Update):
        coordinator = coordinators[node]
        if (coordinator_data := coordinator.data) is not None:
            model_processor = coordinator_data.model
            proxmox_version = f"Proxmox {coordinator_data.version}"

        name = f"{ProxmoxType.Node.capitalize()} {node}"
        identifier = f"{config_entry.entry_id}_{ProxmoxType.Node.upper()}_{node}"
        url = f"https://{host}:{port}/#v1:0:=node/{node}"
        via_device = ("", "")
        model = model_processor

    elif api_category is ProxmoxType.Disk:
        name = f"{api_category.capitalize()} {node}:{resource_id}"
        identifier = f"{config_entry.entry_id}_{api_category.upper()}_{node}_{resource_id}"
        url = f"https://{host}:{port}/#v1:0:=node/{node}::2::::::"
        via_device = (
            DOMAIN,
            f"{config_entry.entry_id}_{ProxmoxType.Node.upper()}_{node}",
        )
        model = f"{cordinator_resource.disk_type.upper()} {cordinator_resource.model}"
        manufacturer = cordinator_resource.vendor
        serial_number = cordinator_resource.serial

    if create:
        device_registry = dr.async_get(hass)
        return device_registry.async_get_or_create(
            config_entry_id=config_entry.entry_id,
            entry_type=dr.DeviceEntryType.SERVICE,
            configuration_url=url,
            identifiers={(DOMAIN, identifier)},
            manufacturer = manufacturer or INTEGRATION_TITLE,
            name=name,
            model=model,
            sw_version=proxmox_version,
            hw_version=None,
            via_device=via_device,
            serial_number = serial_number or None,
        )
    return DeviceInfo(
        entry_type=dr.DeviceEntryType.SERVICE,
        configuration_url=url,
        identifiers={(DOMAIN, identifier)},
        manufacturer = manufacturer or INTEGRATION_TITLE,
        name=name,
        model=model,
        sw_version=proxmox_version,
        hw_version=None,
        via_device=via_device,
        serial_number = serial_number or None,
    )


class ProxmoxClient:
    """A wrapper for the proxmoxer ProxmoxAPI client."""

    _proxmox: ProxmoxAPI

    def __init__(
        self,
        host: str,
        user: str,
        password: str,
        port: int | None = DEFAULT_PORT,
        realm: str | None = DEFAULT_REALM,
        verify_ssl: bool | None = DEFAULT_VERIFY_SSL,
    ) -> None:
        """Initialize the ProxmoxClient."""

        self._host = host
        self._port = port
        self._user = user
        self._realm = realm
        self._password = password
        self._verify_ssl = verify_ssl

    def build_client(self) -> None:
        """Construct the ProxmoxAPI client.

        Allows inserting the realm within the `user` value.
        """

        if "@" in self._user:
            user_id = self._user
        else:
            user_id = f"{self._user}@{self._realm}"

        self._proxmox = ProxmoxAPI(
            self._host,
            port=self._port,
            user=user_id,
            password=self._password,
            verify_ssl=self._verify_ssl,
        )

    def get_api_client(self) -> ProxmoxAPI:
        """Return the ProxmoxAPI client."""
        return self._proxmox


def call_api_post_status(
    self,
    proxmox: ProxmoxAPI,
    api_category: ProxmoxType,
    command: str,
    node: str,
    vm_id: int | None = None,
) -> Any:
    """Make proper api post status calls to set state."""
    result = None
    if command not in ProxmoxCommand:
        raise ValueError("Invalid Command")

    try:
        # Only the START_ALL and STOP_ALL are not part of status API
        if api_category is ProxmoxType.Node and command in [
            ProxmoxCommand.START_ALL,
            ProxmoxCommand.STOP_ALL,
        ]:
            result = proxmox.nodes(node).post(command)
        elif api_category is ProxmoxType.Node:
            result = proxmox(["nodes", node, "status"]).post(command=command)
        else:
            if command == ProxmoxCommand.HIBERNATE:
                result = proxmox(
                    ["nodes", node, api_category, vm_id, "status", ProxmoxCommand.SUSPEND]
                ).post(todisk=1)

            else:
                result = proxmox(
                    ["nodes", node, api_category, vm_id, "status", command]
                ).post()

    except ResourceException as error:
        if error.status_code == 403:
            if api_category is ProxmoxType.Node:
                issue_id=f"{self.config_entry.entry_id}_{node}_command_forbiden"
                resource=f"{api_category.capitalize()} {node}"
                permission_check = f"['perm','/nodes/{node}',['Sys.PowerMgmt']]"
            elif api_category in (ProxmoxType.QEMU, ProxmoxType.LXC):
                issue_id=f"{self.config_entry.entry_id}_{vm_id}_command_forbiden"
                resource=f"{api_category.upper()} {vm_id}"
                permission_check = f"['perm','/vms/{vm_id}',['VM.PowerMgmt']]"
            else:
                raise ValueError(
                    f"Resource not categorized correctly: Proxmox {api_category.upper()} {command} error - {error}",
                ) from error

            async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=IssueSeverity.ERROR,
                translation_key="resource_command_forbiden",
                translation_placeholders={
                    "resource": resource,
                    "user": self.config_entry.data[CONF_USERNAME],
                    "permission": permission_check,
                    "command": command,
                },
            )
            raise ValueError(
                f"Proxmox {api_category.upper()} {command} error - {error}",
            ) from error
    except ConnectTimeout as error:
        raise ValueError(
            f"Proxmox {api_category.upper()} {command} error - {error}",
        ) from error

    return result
