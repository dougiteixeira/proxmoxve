# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Support for Proxmox VE."""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    EVENT_HOMEASSISTANT_STOP,
    Platform,
)
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from homeassistant.helpers import (
    issue_registry as ir,
)
from homeassistant.helpers.device_registry import DeviceInfo
from proxmoxer import AuthenticationError
from proxmoxer.core import ResourceException
from requests.exceptions import (
    ConnectionError as connError,
)
from requests.exceptions import (
    ConnectTimeout,
    RequestException,
    RetryError,
    SSLError,
)
from urllib3.exceptions import InsecureRequestWarning

from .api import ProxmoxClient, auth_error_status, get_api
from .const import (
    CONF_AUTO_DISCOVERY,
    CONF_CLUSTER_HOSTS,
    CONF_CONTAINERS,
    CONF_DISKS_ENABLE,
    CONF_HA_ADMIN_PASSWORD,
    CONF_HA_ADMIN_REALM,
    CONF_HA_ADMIN_TOKEN_NAME,
    CONF_HA_ADMIN_USERNAME,
    CONF_LXC,
    CONF_NODE,
    CONF_NODES,
    CONF_QEMU,
    CONF_REALM,
    CONF_STORAGE,
    CONF_TASKS_ENABLE,
    CONF_TOKEN_NAME,
    CONF_UPDATES_ENABLE,
    CONF_VMS,
    COORDINATORS,
    DEFAULT_PORT,
    DEFAULT_REALM,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    GUEST_AGENT_REFUSALS,
    INTEGRATION_TITLE,
    LOGGER,
    PROXMOX_CLIENT,
    PROXMOX_HA_ADMIN_CLIENT,
    PROXMOX_HA_ADMIN_PERMISSIONS,
    PROXMOX_PERMISSIONS,
    RESOURCE_CALLBACKS,
    TRACKED,
    VERSION_REMOVE_YAML,
    ProxmoxType,
)
from .coordinator import (
    GUEST_AGENT_PRIVILEGES,
    RESOURCES_CACHE,
    ProxmoxBackupCoordinator,
    ProxmoxBackupInfoCoordinator,
    ProxmoxCephCoordinator,
    ProxmoxCertificateCoordinator,
    ProxmoxClusterSummaryCoordinator,
    ProxmoxDiscoveryCoordinator,
    ProxmoxDiskCoordinator,
    ProxmoxHAResourcesCoordinator,
    ProxmoxHAStatusCoordinator,
    ProxmoxLXCCoordinator,
    ProxmoxNodeCoordinator,
    ProxmoxQEMUCoordinator,
    ProxmoxReplicationCoordinator,
    ProxmoxStorageCoordinator,
    ProxmoxSubscriptionCoordinator,
    ProxmoxTaskCoordinator,
    ProxmoxUpdateCoordinator,
    ProxmoxZFSCoordinator,
    forget_untracked_guest_agents,
)
from .discovery import (
    discovered_resources,
    remove_stale_devices,
    selected_resources,
)
from .disk import colliding_disk_wwns, resolve_disk_id
from .issues import (
    NONEXISTENT,
    ResourceLine,
    forget_entry,
    forget_untracked,
    note_resource,
    sweep_legacy_issues,
)
from .permissions import (
    Permissions,
    ProxmoxPrivilege,
    async_fetch_permissions,
    is_granted,
)
from .services import async_register_services
from .storage import (
    STORAGE_PREFIX,
    is_shared_storage_id,
    merge_shared_selection,
    shared_storage_names,
    storage_name,
    tracked_storage_ids,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import Event, HomeAssistant
    from homeassistant.helpers.typing import ConfigType
    from proxmoxer import ProxmoxAPI

    from .models import ProxmoxDiskData, ProxmoxStorageData

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.UPDATE,
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
    async_register_services(hass)
    # import to config flow
    if DOMAIN in config:
        LOGGER.warning(
            # Proxmox VE config flow added and should be removed.
            "Configuration of the Proxmox in YAML is deprecated and should "
            "be removed in %s. Resolve the import issues and remove the "
            "YAML configuration from your configuration.yaml file",
            VERSION_REMOVE_YAML,
        )
        ir.async_create_issue(
            hass,
            DOMAIN,
            "yaml_deprecated",
            breaks_in_ha_version=VERSION_REMOVE_YAML,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="yaml_deprecated",
            translation_placeholders={
                "integration": INTEGRATION_TITLE,
                "platform": DOMAIN,
                "version": VERSION_REMOVE_YAML,
            },
        )
        for conf in config[DOMAIN]:
            if conf.get(CONF_PORT) > 65535 or conf.get(CONF_PORT) <= 0:
                ir.async_create_issue(
                    hass,
                    DOMAIN,
                    f"{conf.get[CONF_HOST]}_{conf.get[CONF_PORT]}_import_invalid_port",
                    is_fixable=False,
                    severity=ir.IssueSeverity.ERROR,
                    translation_key="import_invalid_port",
                    translation_placeholders={
                        "integration": INTEGRATION_TITLE,
                        "platform": DOMAIN,
                        "host": conf.get[CONF_HOST],
                        "port": conf.get[CONF_PORT],
                    },
                )
            else:
                conf[CONF_STORAGE] = []
                hass.async_create_task(
                    hass.config_entries.flow.async_init(
                        DOMAIN,
                        context={"source": SOURCE_IMPORT},
                        data=conf,
                    )
                )
    return True


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
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
            CONF_TOKEN_NAME: config_entry.data.get(CONF_TOKEN_NAME),
            CONF_PASSWORD: config_entry.data.get(CONF_PASSWORD),
            CONF_REALM: config_entry.data.get(CONF_REALM),
            CONF_VERIFY_SSL: config_entry.data.get(CONF_VERIFY_SSL),
            CONF_NODES: node,
            CONF_QEMU: config_entry.data.get(CONF_QEMU),
            CONF_LXC: config_entry.data.get(CONF_LXC),
        }

        hass.config_entries.async_update_entry(
            config_entry,
            data=data_new,
            options={},
            version=2,
            minor_version=1,
        )

        LOGGER.debug("Migration - remove devices: %s", device_identifiers)
        for device_identifier in device_identifiers:
            device_identifier_migrate = {
                (
                    DOMAIN,
                    device_identifier,
                )
            }
            dev_reg = dr.async_get(hass)
            device = dev_reg.async_get_or_create(
                config_entry_id=config_entry.entry_id,
                identifiers=device_identifier_migrate,
            )

            dev_reg.async_remove_device(device.id)

    if config_entry.version == 2:
        device_identifiers = []
        for resource in config_entry.data[CONF_NODES]:
            device_identifiers.append(f"{ProxmoxType.Node.upper()}_{resource}")
        for resource in config_entry.data[CONF_QEMU]:
            device_identifiers.append(f"{ProxmoxType.QEMU.upper()}_{resource}")
        for resource in config_entry.data[CONF_LXC]:
            device_identifiers.append(f"{ProxmoxType.LXC.upper()}_{resource}")

        hass.config_entries.async_update_entry(
            config_entry,
            data=config_entry.data,
            options={},
            version=3,
            minor_version=1,
        )

        LOGGER.debug("Migration - remove devices: %s", device_identifiers)
        for device_identifier in device_identifiers:
            device_identifier_migrate = {
                (
                    DOMAIN,
                    device_identifier,
                )
            }
            dev_reg = dr.async_get(hass)
            device = dev_reg.async_get_or_create(
                config_entry_id=config_entry.entry_id,
                identifiers=device_identifier_migrate,
            )

            dev_reg.async_remove_device(device.id)

    if config_entry.version == 3:
        data_new = {
            CONF_HOST: config_entry.data.get(CONF_HOST),
            CONF_PORT: config_entry.data.get(CONF_PORT),
            CONF_USERNAME: config_entry.data.get(CONF_USERNAME),
            CONF_TOKEN_NAME: config_entry.data.get(CONF_TOKEN_NAME),
            CONF_PASSWORD: config_entry.data.get(CONF_PASSWORD),
            CONF_REALM: config_entry.data.get(CONF_REALM),
            CONF_VERIFY_SSL: config_entry.data.get(CONF_VERIFY_SSL),
            CONF_NODES: config_entry.data.get(CONF_NODES),
            CONF_QEMU: config_entry.data.get(CONF_QEMU),
            CONF_LXC: config_entry.data.get(CONF_LXC),
            CONF_STORAGE: [],
        }
        hass.config_entries.async_update_entry(
            config_entry,
            data=data_new,
            options={},
            version=4,
            minor_version=1,
        )

    if config_entry.version == 4:
        # Storage devices used to be keyed by name; they are recreated under
        # the storage id by the next setup, so the old ones go.
        dev_reg = dr.async_get(hass)
        for storage in config_entry.data.get(CONF_STORAGE, []):
            device = dev_reg.async_get_device_by_identifier(
                (
                    DOMAIN,
                    f"{config_entry.entry_id}_{ProxmoxType.Storage.upper()}_{storage}",
                ),
                config_entry.entry_id,
            )
            if device is not None:
                dev_reg.async_remove_device(device.id)
        # This step never advanced the version, so entries created before
        # the storage id change ran it again on every start and never
        # reached the disk identifier migrations below.
        hass.config_entries.async_update_entry(config_entry, version=5, minor_version=1)

    if config_entry.version == 5:
        # Disk devices move from the device path to a stable disk id.
        await _async_rename_disk_devices(
            hass, config_entry, lambda disk: disk["devpath"]
        )
        hass.config_entries.async_update_entry(config_entry, version=6, minor_version=1)

    if config_entry.version == 6:
        # Disk devices move from the by-id link or serial to the disk id.
        await _async_rename_disk_devices(
            hass,
            config_entry,
            lambda disk: disk["by_id_link"] if "by_id_link" in disk else disk["serial"],
        )
        data_new = {
            CONF_HOST: config_entry.data.get(CONF_HOST),
            CONF_PORT: config_entry.data.get(CONF_PORT),
            CONF_USERNAME: config_entry.data.get(CONF_USERNAME),
            CONF_TOKEN_NAME: config_entry.data.get(CONF_TOKEN_NAME, ""),
            CONF_PASSWORD: config_entry.data.get(CONF_PASSWORD),
            CONF_REALM: config_entry.data.get(CONF_REALM),
            CONF_VERIFY_SSL: config_entry.data.get(CONF_VERIFY_SSL),
            CONF_NODES: config_entry.data.get(CONF_NODES),
            CONF_QEMU: config_entry.data.get(CONF_QEMU),
            CONF_LXC: config_entry.data.get(CONF_LXC),
            CONF_STORAGE: [],
        }
        hass.config_entries.async_update_entry(
            config_entry,
            data=data_new,
            options={},
            version=7,
            minor_version=1,
        )

    LOGGER.info("Migration to version %s successful", config_entry.version)

    return True


async def _async_rename_disk_devices(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    old_id: Callable[[dict[str, Any]], str],
) -> None:
    """
    Move each node's disk devices from an older identifier to the disk id.

    Only devices that actually carry the old identifier are touched. The
    earlier form of this used `async_get_or_create`, which invented a device
    under the old identifier and then renamed it onto an identifier the
    real disk device already had - a duplicate on every start for entries
    whose migration never advanced.
    """
    entry_data = config_entry.data
    proxmox_client = ProxmoxClient(
        host=entry_data[CONF_HOST],
        port=entry_data[CONF_PORT],
        user=entry_data[CONF_USERNAME],
        token_name=entry_data.get(CONF_TOKEN_NAME, ""),
        realm=entry_data[CONF_REALM],
        password=entry_data[CONF_PASSWORD],
        verify_ssl=entry_data[CONF_VERIFY_SSL],
    )
    try:
        await hass.async_add_executor_job(proxmox_client.build_client)
    except (AuthenticationError, RequestException, ResourceException):
        LOGGER.warning("Disk device migration skipped: Proxmox is not reachable")
        return
    proxmox = proxmox_client.get_api_client()

    dev_reg = dr.async_get(hass)
    for node in config_entry.data.get(CONF_NODES, []):
        try:
            disks = await hass.async_add_executor_job(
                get_api, proxmox, f"nodes/{node}/disks/list"
            )
        except (ResourceException, RequestException):
            continue

        disks = disks if isinstance(disks, list) else []
        colliding_wwns = colliding_disk_wwns(disks)
        for disk in disks:
            try:
                old = old_id(disk)
            except KeyError:
                continue
            prefix = f"{config_entry.entry_id}_{ProxmoxType.Disk.upper()}_{node}_"
            device = dev_reg.async_get_device_by_identifier(
                (DOMAIN, f"{prefix}{old}"), config_entry.entry_id
            )
            new_identifier = (
                DOMAIN,
                f"{prefix}{resolve_disk_id(disk, colliding_wwns=colliding_wwns)}",
            )
            if device is None or new_identifier in device.identifiers:
                continue
            if (
                dev_reg.async_get_device_by_identifier(
                    new_identifier, config_entry.entry_id
                )
                is not None
            ):
                # The new device already exists; the old one is a leftover.
                dev_reg.async_remove_device(device.id)
                continue
            dev_reg.async_update_device(
                device_id=device.id, new_identifiers={new_identifier}
            )


async def _get_api_or_retry_setup(
    hass: HomeAssistant,
    proxmox: ProxmoxAPI,
    api_path: str,
    host: str,
) -> dict | list | None:
    """
    Read an API path during setup, asking to be retried if the host is down.

    An exception escaping async_setup_entry leaves the entry in SETUP_ERROR,
    which Home Assistant does not retry - the integration then stays dead until
    it is reloaded by hand, even once Proxmox is back. ConfigEntryNotReady is
    what asks for the retry. build_client already translates these exceptions,
    but it only reaches the network when authenticating with a password; with
    an API token it constructs the client offline, so the first call to fail is
    this one.
    """
    try:
        return await hass.async_add_executor_job(get_api, proxmox, api_path)
    except AuthenticationError as error:
        raise ConfigEntryAuthFailed from error
    except (
        SSLError,
        ConnectTimeout,
        RetryError,
        connError,
        ResourceException,
    ) as error:
        msg = f"Connection is unreachable to host {host}"
        raise ConfigEntryNotReady(msg) from error


def clear_stale_resource_issues(
    hass: HomeAssistant, config_entry: ConfigEntry, tracked: dict[str, list[Any]]
) -> None:
    """
    Drop the repair lines for resources this setup no longer tracks.

    The "does not exist" line tells you to remove the resource in the
    options. Doing that reloads the entry, and setup then never looks at
    the resource again - so nothing else would take the line off. The
    per-resource repairs of earlier versions are swept out on the way.
    """
    still_tracked = {
        str(resource_id) for ids in tracked.values() for resource_id in ids
    }
    sweep_legacy_issues(hass, config_entry)
    forget_untracked(hass, config_entry, still_tracked)
    forget_untracked_guest_agents(hass, config_entry, still_tracked)


def _resource_nonexistent_issue(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    resource_type: str,
    resource: str | int,
    permission: str,
) -> None:
    """Put a tracked resource the cluster does not list on the repair."""
    note_resource(
        hass,
        config_entry,
        NONEXISTENT,
        str(resource),
        ResourceLine(f"{resource_type} {resource}", permission, str(resource)),
        listed=True,
    )


def _resource_exists_again(
    hass: HomeAssistant, config_entry: ConfigEntry, resource: str | int
) -> None:
    """Take a resource the cluster lists off the repair."""
    note_resource(hass, config_entry, NONEXISTENT, str(resource), listed=False)


async def _async_setup_node(  # noqa: PLR0917
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    proxmox: ProxmoxAPI,
    node: str,
    coordinators: dict[str, Any],
    nodes_api: list | dict | None,
    permissions: Permissions | None = None,
) -> ProxmoxNodeCoordinator | None:
    """
    Create every coordinator a node needs, at setup or when discovered later.

    Returns the node coordinator, or None when the cluster does not list the
    node - a repair issue says so then.
    """
    if node not in [
        node_proxmox["node"]
        for node_proxmox in (nodes_api if isinstance(nodes_api, list) else [])
        if isinstance(node_proxmox, dict)
    ]:
        _resource_nonexistent_issue(
            hass,
            config_entry,
            ProxmoxType.Node.capitalize(),
            node,
            f"['perm','/nodes/{node}',['Sys.Audit']]",
        )
        return None

    _resource_exists_again(hass, config_entry, node)
    coordinator_node = ProxmoxNodeCoordinator(
        hass=hass,
        proxmox=proxmox,
        config_entry=config_entry,
        api_category=ProxmoxType.Node,
        node_name=node,
    )
    await coordinator_node.async_refresh()
    coordinators[f"{ProxmoxType.Node}_{node}"] = coordinator_node

    # Reading `apt/update` needs Sys.Modify on the node - a management
    # privilege a read-only setup deliberately does not hold. Where the
    # credentials' privileges are known and lack it, or the option says no,
    # there is no update coordinator at all: no entity that can never know
    # anything, and no repair demanding a permission the person chose not
    # to give.
    if not config_entry.options.get(CONF_UPDATES_ENABLE, True):
        LOGGER.debug("Node %s: package updates switched off in the options", node)
    elif permissions is None or is_granted(
        permissions, f"/nodes/{node}", ProxmoxPrivilege.SYS_MODIFY
    ):
        coordinator_updates = ProxmoxUpdateCoordinator(
            hass=hass,
            proxmox=proxmox,
            config_entry=config_entry,
            api_category=ProxmoxType.Update,
            node_name=node,
        )
        await coordinator_updates.async_refresh()
        coordinators[f"{ProxmoxType.Update}_{node}"] = coordinator_updates
    else:
        LOGGER.debug(
            "Node %s: credentials lack Sys.Modify, skipping package updates", node
        )

    coordinator_certificate = ProxmoxCertificateCoordinator(
        hass=hass,
        proxmox=proxmox,
        config_entry=config_entry,
        node_name=node,
    )
    await coordinator_certificate.async_refresh()
    coordinators[f"{ProxmoxType.Certificate}_{node}"] = coordinator_certificate

    coordinator_subscription = ProxmoxSubscriptionCoordinator(
        hass=hass,
        proxmox=proxmox,
        config_entry=config_entry,
        node_name=node,
    )
    await coordinator_subscription.async_refresh()
    coordinators[f"{ProxmoxType.Subscription}_{node}"] = coordinator_subscription

    coordinator_replication = ProxmoxReplicationCoordinator(
        hass=hass,
        proxmox=proxmox,
        config_entry=config_entry,
        node_name=node,
    )
    await coordinator_replication.async_refresh()
    coordinators[f"{ProxmoxType.Replication}_{node}"] = coordinator_replication

    coordinator_backup = ProxmoxBackupCoordinator(
        hass=hass,
        proxmox=proxmox,
        config_entry=config_entry,
        node_name=node,
    )
    await coordinator_backup.async_refresh()
    coordinators[f"{ProxmoxType.Backup}_{node}"] = coordinator_backup

    if config_entry.options.get(CONF_TASKS_ENABLE, True):
        coordinator_tasks = ProxmoxTaskCoordinator(
            hass=hass,
            proxmox=proxmox,
            config_entry=config_entry,
            api_category=ProxmoxType.Tasks,
            node_name=node,
        )
        await coordinator_tasks.async_refresh()
        coordinators[f"{ProxmoxType.Tasks}_{node}"] = coordinator_tasks

    if config_entry.options.get(CONF_DISKS_ENABLE, True):
        try:
            disks = await hass.async_add_executor_job(
                get_api, proxmox, f"nodes/{node}/disks/list"
            )
        except ResourceException:
            return coordinator_node

        disks = disks if disks is not None else []
        colliding_wwns = colliding_disk_wwns(disks)
        coordinators_disk = []
        for disk in disks:
            coordinator_disk = ProxmoxDiskCoordinator(
                hass=hass,
                proxmox=proxmox,
                config_entry=config_entry,
                api_category=ProxmoxType.Disk,
                node_name=node,
                disk_id=resolve_disk_id(disk, colliding_wwns=colliding_wwns),
            )
            await coordinator_disk.async_refresh()
            coordinators_disk.append(coordinator_disk)
        coordinators[f"{ProxmoxType.Disk}_{node}"] = coordinators_disk

        try:
            pools = await hass.async_add_executor_job(
                get_api, proxmox, f"nodes/{node}/disks/zfs"
            )
        except ResourceException as e:
            LOGGER.exception(e)
            return coordinator_node

        coordinators_zfs = []
        for pool in pools if pools is not None else []:
            coordinator_zfs = ProxmoxZFSCoordinator(
                hass=hass,
                proxmox=proxmox,
                config_entry=config_entry,
                api_category=ProxmoxType.ZFS,
                node_name=node,
                zfs_id=pool["name"],
            )
            await coordinator_zfs.async_refresh()
            coordinators_zfs.append(coordinator_zfs)
        coordinators[f"{ProxmoxType.ZFS}_{node}"] = coordinators_zfs

    return coordinator_node


async def _async_setup_guest(  # noqa: PLR0917
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    proxmox: ProxmoxAPI,
    api_category: ProxmoxType,
    vm_id: str | int,
    coordinators: dict[str, Any],
    resources: list | dict | None,
) -> bool:
    """
    Create the coordinator of a VM or container, at setup or when discovered.

    Returns whether the cluster lists the guest; a repair issue says so when
    it does not.
    """
    if int(vm_id) not in [
        (int(resource["vmid"]) if "vmid" in resource else None)
        for resource in (resources if isinstance(resources, list) else [])
        if isinstance(resource, dict)
    ]:
        _resource_nonexistent_issue(
            hass,
            config_entry,
            api_category.upper(),
            vm_id,
            f"['perm','/vms/{vm_id}',['VM.Audit']]",
        )
        return False

    _resource_exists_again(hass, config_entry, vm_id)
    if api_category is ProxmoxType.QEMU:
        coordinator: ProxmoxQEMUCoordinator | ProxmoxLXCCoordinator = (
            ProxmoxQEMUCoordinator(
                hass=hass,
                proxmox=proxmox,
                config_entry=config_entry,
                api_category=ProxmoxType.QEMU,
                qemu_id=vm_id,
            )
        )
    else:
        coordinator = ProxmoxLXCCoordinator(
            hass=hass,
            proxmox=proxmox,
            config_entry=config_entry,
            api_category=ProxmoxType.LXC,
            container_id=vm_id,
        )
    await coordinator.async_refresh()
    coordinators[f"{api_category}_{vm_id}"] = coordinator
    return True


async def _async_setup_storage(  # noqa: PLR0917
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    proxmox: ProxmoxAPI,
    storage_id: str,
    coordinators: dict[str, Any],
    resources: list | dict | None,
) -> bool:
    """
    Create the coordinator of a storage, at setup or when discovered later.

    Returns whether the cluster lists the storage; a repair issue says so
    when it does not.
    """
    # Shared storage is tracked under its node-less id, which the listing
    # itself never carries; `tracked_storage_ids` speaks both forms.
    if storage_id not in tracked_storage_ids(resources):
        _resource_nonexistent_issue(
            hass,
            config_entry,
            ProxmoxType.Storage.capitalize(),
            storage_id,
            f"['perm','{storage_id}',['Datastore.Audit'],'any',1]",
        )
        return False

    _resource_exists_again(hass, config_entry, storage_id)
    coordinator_storage = ProxmoxStorageCoordinator(
        hass=hass,
        proxmox=proxmox,
        config_entry=config_entry,
        api_category=ProxmoxType.Storage,
        storage_id=storage_id,
    )
    await coordinator_storage.async_refresh()
    coordinators[f"{ProxmoxType.Storage}_{storage_id}"] = coordinator_storage
    return True


# The coordinators a node owns, besides the node coordinator itself; the
# last two are lists, one coordinator per disk or pool.
NODE_COORDINATOR_TYPES: tuple[ProxmoxType, ...] = (
    ProxmoxType.Node,
    ProxmoxType.Update,
    ProxmoxType.Certificate,
    ProxmoxType.Subscription,
    ProxmoxType.Replication,
    ProxmoxType.Backup,
    ProxmoxType.Tasks,
    ProxmoxType.Disk,
    ProxmoxType.ZFS,
)


async def _async_drop_coordinators(
    coordinators: dict[str, Any], api_category: ProxmoxType, resource_id: str
) -> None:
    """Stop and forget the coordinators of a resource the cluster no longer has."""
    keys = (
        [f"{owned}_{resource_id}" for owned in NODE_COORDINATOR_TYPES]
        if api_category is ProxmoxType.Node
        else [f"{api_category}_{resource_id}"]
    )
    for key in keys:
        coordinator = coordinators.pop(key, None)
        if coordinator is None:
            continue
        for single in coordinator if isinstance(coordinator, list) else [coordinator]:
            await single.async_shutdown()


async def _learn_cluster_hosts(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    client: ProxmoxClient,
    proxmox: ProxmoxAPI,
) -> str | None:
    """
    Tell the client what the other nodes of the cluster answer on.

    `cluster/status` lists every node with the address it joined the cluster
    on. Should the configured host stop answering, the client tries those in
    turn instead of taking the whole cluster out of Home Assistant. Not
    being able to read the list - a single node, or credentials without
    Sys.Audit on `/` - changes nothing about setup.

    Returns the name of the node the configured host is, which the same
    listing marks as `local`, or None when that could not be read.
    """
    try:
        status = await hass.async_add_executor_job(get_api, proxmox, "cluster/status")
    except (AuthenticationError, RequestException, ResourceException) as error:
        LOGGER.debug("Cluster members not read, no fallback hosts: %s", error)
        return None
    nodes = [
        entry
        for entry in (status if isinstance(status, list) else [])
        if isinstance(entry, dict) and entry.get("type") == "node"
    ]
    client.learn_hosts([entry["ip"] for entry in nodes if entry.get("ip")])
    if len(client.hosts) > 1:
        LOGGER.debug("Fallback hosts for %s: %s", client.host, client.hosts[1:])
    _remember_cluster_hosts(hass, config_entry, client)
    local = next((entry for entry in nodes if entry.get("local")), None)
    return str(local["name"]) if local and local.get("name") else None


def _remember_cluster_hosts(
    hass: HomeAssistant, config_entry: ConfigEntry, client: ProxmoxClient
) -> None:
    """
    Keep the cluster's other addresses in the entry, for the next start.

    They are read from `cluster/status`, which needs a host that answers -
    so at the start of a setup, while the configured host is down, the only
    addresses there are are the ones from the last time it was up. Written
    only when they changed, and never emptied by a read that did not
    happen: a single node, or credentials without Sys.Audit on `/`, returns
    before this.
    """
    fallbacks = [host for host in client.hosts if host != config_entry.data[CONF_HOST]]
    if list(config_entry.data.get(CONF_CLUSTER_HOSTS, [])) == fallbacks:
        return
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, CONF_CLUSTER_HOSTS: fallbacks}
    )


def async_merge_shared_storages(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    resources: Any,
    preferred_node: str | None,
) -> None:
    """
    Bring a selection made per node up to the one-device form for shared storage.

    Until now a shared storage was tracked once per node, as
    `storage/<node>/<name>`, and a cluster of four showed the same NFS
    export four times. It is tracked as `storage/<name>` from here on.
    Where the selection still carries the per-node ids of a storage the
    cluster marks as shared, one of them keeps the device and every entity
    - the one on the node the configured host is, where picked, otherwise
    the first picked - under the new id, so history is kept; the others
    lose their device. Runs at every setup and does nothing once the
    selection is current, which also covers an entry that was set up
    while the cluster could not be asked.
    """
    selection = [str(value) for value in config_entry.data.get(CONF_STORAGE, [])]
    shared = shared_storage_names(resources)
    new_selection, keepers, dropped = merge_shared_selection(
        selection, shared, preferred_node
    )
    if new_selection == selection:
        return

    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    prefix = f"{config_entry.entry_id}_{ProxmoxType.Storage.upper()}_"
    for new_id, old_id in keepers.items():
        old_identifier = (DOMAIN, prefix + old_id.replace(STORAGE_PREFIX, ""))
        new_identifier = (DOMAIN, prefix + new_id.replace(STORAGE_PREFIX, ""))
        device = dev_reg.async_get_device_by_identifier(
            old_identifier, config_entry.entry_id
        )
        if device is not None and new_identifier not in device.identifiers:
            dev_reg.async_update_device(
                device_id=device.id, new_identifiers={new_identifier}
            )
        for entity in er.async_entries_for_config_entry(ent_reg, config_entry.entry_id):
            old_unique = f"{config_entry.entry_id}_{old_id}_"
            if entity.unique_id.startswith(old_unique):
                ent_reg.async_update_entity(
                    entity.entity_id,
                    new_unique_id=f"{config_entry.entry_id}_{new_id}_"
                    + entity.unique_id[len(old_unique) :],
                )
    for old_id in dropped:
        device = dev_reg.async_get_device_by_identifier(
            (DOMAIN, prefix + old_id.replace(STORAGE_PREFIX, "")),
            config_entry.entry_id,
        )
        if device is not None:
            dev_reg.async_remove_device(device.id)

    LOGGER.info(
        "Shared storage is tracked once now: %s kept, %s merged away",
        list(keepers.values()),
        dropped,
    )
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, CONF_STORAGE: new_selection}
    )


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up the platform."""
    hass.data.setdefault(DOMAIN, {})
    entry_data = config_entry.data

    host = entry_data[CONF_HOST]
    port = entry_data[CONF_PORT]
    user = entry_data[CONF_USERNAME]
    token_name = entry_data.get(CONF_TOKEN_NAME, "")
    realm = entry_data[CONF_REALM]
    password = entry_data[CONF_PASSWORD]
    verify_ssl = entry_data[CONF_VERIFY_SSL]

    # Construct an API client with the given data for the given host
    proxmox_client = ProxmoxClient(
        host=host,
        port=port,
        user=user,
        token_name=token_name,
        realm=realm,
        password=password,
        verify_ssl=verify_ssl,
        fallback_hosts=entry_data.get(CONF_CLUSTER_HOSTS, []),
    )
    try:
        await hass.async_add_executor_job(proxmox_client.build_client)
    except AuthenticationError as error:
        # proxmoxer raises the same error for a refused password and for an
        # API that is up but not issuing tickets yet, as during boot. Only
        # 401 says anything about the credentials; the rest is "try later".
        if auth_error_status(error) not in (None, 401):
            raise ConfigEntryNotReady(str(error)) from error
        raise ConfigEntryAuthFailed from error
    except SSLError as error:
        msg = (
            "Unable to verify proxmox server SSL. Try using 'verify_ssl: false' "
            f"for proxmox instance {host}:{port}"
        )
        raise ConfigEntryNotReady(msg) from error
    except ConnectTimeout as error:
        msg = f"Connection to host {host} timed out during setup"
        raise ConfigEntryNotReady(msg) from error
    except RetryError as error:
        msg = f"Connection is unreachable to host {host}"
        raise ConfigEntryNotReady(msg) from error
    except connError as error:
        msg = f"Connection is unreachable to host {host}"
        raise ConfigEntryNotReady(msg) from error
    except ResourceException as error:
        raise ConfigEntryNotReady from error

    proxmox = await hass.async_add_executor_job(proxmox_client.get_api_client)
    local_node = await _learn_cluster_hosts(hass, config_entry, proxmox_client, proxmox)

    coordinators: dict[
        str,
        ProxmoxNodeCoordinator
        | ProxmoxQEMUCoordinator
        | ProxmoxLXCCoordinator
        | ProxmoxStorageCoordinator
        | ProxmoxTaskCoordinator
        | ProxmoxUpdateCoordinator
        | list[ProxmoxDiskCoordinator]
        | list[ProxmoxZFSCoordinator],
    ] = {}
    nodes_add_device = []

    resources = await _get_api_or_retry_setup(hass, proxmox, "cluster/resources", host)
    async_merge_shared_storages(hass, config_entry, resources, local_node)

    # What these credentials may do, so the button platform can leave out
    # buttons that could only ever fail. None when it cannot be read, in
    # which case nothing is left out.
    permissions = await async_fetch_permissions(hass, proxmox)

    # What this setup tracks. By default the selection from the config
    # entry; with automatic discovery on, the cluster's own list - decided
    # here, before the coordinators are built from it, and followed
    # afterwards by a coordinator that adds and removes resources as they
    # come and go. The selection itself stays as it is, so switching
    # discovery off again brings it back.
    selection = selected_resources(config_entry)
    auto_discovery = config_entry.options.get(CONF_AUTO_DISCOVERY, False)
    if auto_discovery and isinstance(resources, list):
        tracked = discovered_resources(resources)
        remove_stale_devices(hass, config_entry, tracked)
    else:
        tracked = selection
    clear_stale_resource_issues(hass, config_entry, tracked)

    nodes_api = await _get_api_or_retry_setup(hass, proxmox, "nodes", host)
    for node in tracked[CONF_NODES]:
        coordinator_node = await _async_setup_node(
            hass, config_entry, proxmox, node, coordinators, nodes_api, permissions
        )
        if coordinator_node is not None and coordinator_node.data is not None:
            nodes_add_device.append(node)

    for vm_id in tracked[CONF_QEMU]:
        await _async_setup_guest(
            hass,
            config_entry,
            proxmox,
            ProxmoxType.QEMU,
            vm_id,
            coordinators,
            resources,
        )

    for container_id in tracked[CONF_LXC]:
        await _async_setup_guest(
            hass,
            config_entry,
            proxmox,
            ProxmoxType.LXC,
            container_id,
            coordinators,
            resources,
        )

    for storage_id in tracked[CONF_STORAGE]:
        await _async_setup_storage(
            hass, config_entry, proxmox, storage_id, coordinators, resources
        )

    # The cluster at a glance, for every setup: no privilege beyond what
    # the primary credentials already use for the resource list.
    summary_coordinator = ProxmoxClusterSummaryCoordinator(
        hass=hass, proxmox=proxmox, config_entry=config_entry
    )
    await summary_coordinator.async_refresh()
    coordinators[f"{ProxmoxType.Proxmox}_summary"] = summary_coordinator

    # Optional, separate higher-privilege credentials for cluster-wide HA
    # arm/disarm (needs Sys.Console on '/') and HA-resource membership
    # (needs Sys.Audit on '/') — both broader than the least-privilege scopes
    # the rest of the integration needs, so this stays opt-in and its failure
    # must not break the primary integration setup.
    proxmox_ha_admin_client = None
    ha_admin_user = config_entry.data.get(CONF_HA_ADMIN_USERNAME)
    ha_admin_password = config_entry.data.get(CONF_HA_ADMIN_PASSWORD)
    if ha_admin_user and ha_admin_password:
        candidate_client = ProxmoxClient(
            # The node the primary client ended up on, and the same places
            # to go from there - the configured host may be the one down.
            host=proxmox_client.host,
            port=port,
            user=ha_admin_user,
            token_name=config_entry.data.get(CONF_HA_ADMIN_TOKEN_NAME, ""),
            realm=config_entry.data.get(CONF_HA_ADMIN_REALM, DEFAULT_REALM),
            password=ha_admin_password,
            verify_ssl=verify_ssl,
            fallback_hosts=proxmox_client.hosts,
        )
        try:
            await hass.async_add_executor_job(candidate_client.build_client)
        except (
            AuthenticationError,
            SSLError,
            ConnectTimeout,
            RetryError,
            connError,
            ResourceException,
        ):
            LOGGER.exception(
                "Unable to authenticate with the optional cluster HA admin "
                "credentials; the Arm/Disarm HA buttons, the HA managed "
                "sensors and the cluster HA status sensors will not be created"
            )
        else:
            proxmox_ha_admin_client = candidate_client

    ha_resources_coordinator = None
    ha_admin_permissions = None
    if proxmox_ha_admin_client is not None:
        proxmox_ha_admin = await hass.async_add_executor_job(
            proxmox_ha_admin_client.get_api_client
        )
        ha_admin_permissions = await async_fetch_permissions(hass, proxmox_ha_admin)
        ha_resources_coordinator = ProxmoxHAResourcesCoordinator(
            hass=hass,
            proxmox=proxmox_ha_admin,
            config_entry=config_entry,
        )
        await ha_resources_coordinator.async_refresh()
        coordinators[f"{ProxmoxType.Proxmox}_ha_resources"] = ha_resources_coordinator

        ha_status_coordinator = ProxmoxHAStatusCoordinator(
            hass=hass,
            proxmox=proxmox_ha_admin,
            config_entry=config_entry,
        )
        await ha_status_coordinator.async_refresh()
        coordinators[f"{ProxmoxType.Proxmox}_ha_status"] = ha_status_coordinator

        backup_info_coordinator = ProxmoxBackupInfoCoordinator(
            hass=hass,
            proxmox=proxmox_ha_admin,
            config_entry=config_entry,
        )
        await backup_info_coordinator.async_refresh()
        coordinators[f"{ProxmoxType.Proxmox}_backup_info"] = backup_info_coordinator

        # Most clusters run no Ceph, where this endpoint simply fails. Probing
        # once keeps a permanently failing coordinator - and its error every
        # update - off the majority of installations.
        try:
            ceph_available = (
                await hass.async_add_executor_job(
                    get_api, proxmox_ha_admin, "cluster/ceph/status"
                )
                is not None
            )
        except (
            AuthenticationError,
            SSLError,
            ConnectTimeout,
            RetryError,
            connError,
            ResourceException,
        ):
            ceph_available = False
            LOGGER.debug("No Ceph cluster found, skipping its sensor")

        if ceph_available:
            ceph_coordinator = ProxmoxCephCoordinator(
                hass=hass,
                proxmox=proxmox_ha_admin,
                config_entry=config_entry,
            )
            await ceph_coordinator.async_refresh()
            coordinators[f"{ProxmoxType.Proxmox}_ceph"] = ceph_coordinator

    config_entry.runtime_data = {
        PROXMOX_CLIENT: proxmox_client,
        PROXMOX_HA_ADMIN_CLIENT: proxmox_ha_admin_client,
        PROXMOX_PERMISSIONS: permissions,
        PROXMOX_HA_ADMIN_PERMISSIONS: ha_admin_permissions,
        COORDINATORS: coordinators,
        RESOURCE_CALLBACKS: [],
        TRACKED: tracked,
    }

    if auto_discovery:

        async def _async_add_resource(
            api_category: ProxmoxType, resource_id: str
        ) -> None:
            """Build the coordinators, device and entities of a new resource."""
            try:
                if api_category is ProxmoxType.Node:
                    listing = await hass.async_add_executor_job(
                        get_api, proxmox, "nodes"
                    )
                else:
                    listing = await hass.async_add_executor_job(
                        get_api, proxmox, "cluster/resources"
                    )
            except (
                AuthenticationError,
                SSLError,
                ConnectTimeout,
                RetryError,
                connError,
                ResourceException,
            ) as error:
                LOGGER.warning(
                    "Discovery: could not set up %s %s: %s",
                    api_category,
                    resource_id,
                    error,
                )
                return

            if api_category is ProxmoxType.Node:
                coordinator_node = await _async_setup_node(
                    hass,
                    config_entry,
                    proxmox,
                    resource_id,
                    coordinators,
                    listing,
                    permissions,
                )
                if coordinator_node is None:
                    return
                if coordinator_node.data is not None:
                    device_info(
                        hass=hass,
                        config_entry=config_entry,
                        api_category=ProxmoxType.Node,
                        node=resource_id,
                        create=True,
                    )
            elif api_category is ProxmoxType.Storage:
                if not await _async_setup_storage(
                    hass, config_entry, proxmox, resource_id, coordinators, listing
                ):
                    return
            elif not await _async_setup_guest(
                hass,
                config_entry,
                proxmox,
                api_category,
                resource_id,
                coordinators,
                listing,
            ):
                return

            for add_entities in config_entry.runtime_data[RESOURCE_CALLBACKS]:
                await add_entities(api_category, resource_id)

        async def _async_remove_resource(
            api_category: ProxmoxType, resource_id: str
        ) -> None:
            """Stop polling a resource the cluster no longer has."""
            await _async_drop_coordinators(coordinators, api_category, resource_id)

        discovery_coordinator = ProxmoxDiscoveryCoordinator(
            hass=hass,
            proxmox=proxmox,
            config_entry=config_entry,
            add_resource=_async_add_resource,
            remove_resource=_async_remove_resource,
        )
        # No entity listens to this coordinator, and a coordinator without a
        # listener never polls. A no-op listener puts it on the schedule; no
        # refresh now, since setup just applied the same listing.
        config_entry.async_on_unload(
            discovery_coordinator.async_add_listener(lambda: None)
        )
        coordinators[f"{ProxmoxType.Proxmox}_discovery"] = discovery_coordinator

    async def _stop_polling(_event: Event) -> None:
        """
        Stop scheduling refreshes once Home Assistant is shutting down.

        Every poll runs in an executor thread and blocks there until the
        Proxmox API answers or the request times out. A thread cannot be
        cancelled, so a refresh that starts late holds up shutdown - which is
        what Home Assistant means by "Integrations should cancel non-critical
        tasks when receiving the stop event". Shutting the coordinators down
        stops new polls from being scheduled; one already in flight still
        finishes, bounded by the client's timeout.
        """
        for coordinator in coordinators.values():
            for single in (
                coordinator if isinstance(coordinator, list) else [coordinator]
            ):
                await single.async_shutdown()

    config_entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _stop_polling)
    )

    # The cluster device carries the summary, the HA features and every
    # shared storage; it has to exist before those hang their entities on it.
    device_info(
        hass=hass,
        config_entry=config_entry,
        api_category=ProxmoxType.Proxmox,
        create=True,
    )

    for node in nodes_add_device:
        device_info(
            hass=hass,
            config_entry=config_entry,
            api_category=ProxmoxType.Node,
            node=node,
            create=True,
        )

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    hass.data.get(DOMAIN, {}).get(GUEST_AGENT_REFUSALS, {}).pop(entry.entry_id, None)
    for feature in GUEST_AGENT_PRIVILEGES:
        ir.async_delete_issue(hass, DOMAIN, f"{entry.entry_id}_guest_agent_{feature}")
    forget_entry(hass, entry.entry_id)
    hass.data.get(DOMAIN, {}).get(RESOURCES_CACHE, {}).pop(entry.entry_id, None)
    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Remove a config entry from a device."""
    dev_reg = dr.async_get(hass)
    dev_reg.async_remove_device(device_entry.id)
    LOGGER.debug("Device %s (%s) removed", device_entry.name, device_entry.id)
    return True


def device_info(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    api_category: ProxmoxType,
    node: str | None = None,
    resource_id: int | None = None,
    *,
    create: bool | None = False,
    cordinator_resource: ProxmoxDiskData | ProxmoxStorageData | None = None,
):
    """Return the Device Info."""
    coordinators = config_entry.runtime_data[COORDINATORS]

    host = config_entry.data[CONF_HOST]
    port = config_entry.data[CONF_PORT]

    proxmox_version = None
    manufacturer = None
    serial_number = None
    connections: set[tuple[str, str]] = set()
    if api_category is ProxmoxType.Proxmox:
        name = "Proxmox Cluster"
        identifier = f"{config_entry.entry_id}_cluster"
        url = f"https://{host}:{port}/#v1:0:=cluster/ha"
        via_device = None
        model = "Cluster"

    elif api_category in (ProxmoxType.QEMU, ProxmoxType.LXC):
        coordinator = coordinators[f"{api_category}_{resource_id}"]
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
        coordinator = coordinators[f"{api_category}_{resource_id}"]
        if (coordinator_data := coordinator.data) is not None:
            node = coordinator_data.node

        name = cordinator_resource.name
        identifier = f"{config_entry.entry_id}_{api_category.upper()}_{resource_id.replace('storage/', '')}"
        if is_shared_storage_id(resource_id):
            # One device for the whole cluster; the web interface still
            # wants a node in the address, so use the one answering for it.
            url = f"https://{host}:{port}/#v1:0:=storage/{node}/{storage_name(resource_id)}"
            via_device = (DOMAIN, f"{config_entry.entry_id}_cluster")
            model = "Shared storage"
        else:
            url = f"https://{host}:{port}/#v1:0:={resource_id}"
            via_device = (
                DOMAIN,
                f"{config_entry.entry_id}_{ProxmoxType.Node.upper()}_{node}",
            )
            model = api_category.capitalize()

    elif api_category in (ProxmoxType.Node, ProxmoxType.Update):
        coordinator = coordinators[f"{ProxmoxType.Node}_{node}"]
        if (coordinator_data := coordinator.data) is not None:
            model_processor = coordinator_data.model
            proxmox_version = f"Proxmox {coordinator_data.version}"
            connections = {
                (dr.CONNECTION_NETWORK_MAC, mac)
                for mac in coordinator_data.mac_addresses
            }

        name = f"{ProxmoxType.Node.capitalize()} {node}"
        identifier = f"{config_entry.entry_id}_{ProxmoxType.Node.upper()}_{node}"
        url = f"https://{host}:{port}/#v1:0:=node/{node}"
        via_device = None
        model = model_processor

    elif api_category is ProxmoxType.Disk:
        model = cordinator_resource.model
        name = f"{api_category.capitalize()} {node}: {model.replace('_', ' ')}"
        identifier = (
            f"{config_entry.entry_id}_{api_category.upper()}_{node}_{resource_id}"
        )
        url = f"https://{host}:{port}/#v1:0:=node/{node}::2::::::"
        via_device = (
            DOMAIN,
            f"{config_entry.entry_id}_{ProxmoxType.Node.upper()}_{node}",
        )
        if cordinator_resource is None:
            model = api_category.capitalize()
        else:
            disk_type = cordinator_resource.disk_type
            model = (
                f"{disk_type.upper()} {model.replace('_', ' ')} "
                if disk_type is not None
                else f"{disk_type}{model.replace('_', ' ')}"
            )
            manufacturer = cordinator_resource.vendor
            serial_number = cordinator_resource.serial

    elif api_category is ProxmoxType.ZFS:
        name = f"{api_category.upper()} {node}: {resource_id}"
        identifier = (
            f"{config_entry.entry_id}_{api_category.upper()}_{node}_{resource_id}"
        )
        url = f"https://{host}:{port}/#v1:0:=node/{node}:4:=zfs::::::"
        via_device = (
            DOMAIN,
            f"{config_entry.entry_id}_{ProxmoxType.Node.upper()}_{node}",
        )
        model = api_category.upper()
        manufacturer = None
        serial_number = None

    # `via_device` is deprecated and stops working in Home Assistant 2027.8.0:
    # identifiers are only unique within a config entry, so an identifier pair
    # no longer points at one device unambiguously. The registry wants the
    # parent's id instead, which means resolving it here - scoped to this entry,
    # so the lookup cannot be ambiguous either.
    #
    # Resolving also settles a separate complaint: naming a parent that does not
    # exist made Home Assistant log a report while dropping the link anyway.
    # That happens for a guest, storage, disk or pool on a node the user did not
    # select, so no node device was created for it. Leaving the link out loses
    # nothing, and update_guest_device() attaches a guest to its node as soon as
    # that node has a device.
    via_device_id: str | None = None
    if via_device is not None:
        parent = dr.async_get(hass).async_get_device_by_identifier(
            via_device, config_entry.entry_id
        )
        via_device_id = parent.id if parent else None

    if create:
        device_registry = dr.async_get(hass)
        return device_registry.async_get_or_create(
            config_entry_id=config_entry.entry_id,
            entry_type=dr.DeviceEntryType.SERVICE,
            configuration_url=url,
            identifiers={(DOMAIN, identifier)},
            connections=connections,
            manufacturer=manufacturer or INTEGRATION_TITLE,
            name=name,
            model=model,
            sw_version=proxmox_version,
            hw_version=None,
            via_device_id=via_device_id,
            serial_number=serial_number or None,
        )
    return DeviceInfo(
        entry_type=dr.DeviceEntryType.SERVICE,
        configuration_url=url,
        identifiers={(DOMAIN, identifier)},
        connections=connections,
        manufacturer=manufacturer or INTEGRATION_TITLE,
        name=name,
        model=model,
        sw_version=proxmox_version,
        hw_version=None,
        via_device_id=via_device_id,
        serial_number=serial_number or None,
    )


async def async_migrate_old_unique_ids(
    hass: HomeAssistant, platform: Platform, entities
) -> None:
    """Migration of the unique id of disk entities."""
    registry = er.async_get(hass)
    for entity in entities:
        entity_id = registry.async_get_entity_id(
            platform, DOMAIN, entity["old_unique_id"]
        )
        if entity_id is not None:
            LOGGER.debug(
                "Migrating unique_id %s: from [%s] to [%s]",
                entity_id,
                entity["old_unique_id"],
                entity["new_unique_id"],
            )
            registry.async_update_entity(
                entity_id, new_unique_id=entity["new_unique_id"]
            )
