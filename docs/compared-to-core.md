[← README](https://github.com/dougiteixeira/proxmoxve#readme) · [Entities](entities.md) · [Actions](actions.md) · [Hardware sensors](hardware-sensors.md) · [Permissions](permissions.md) · [Behaviour](behaviour.md) · [Troubleshooting](troubleshooting.md) · [Compared with core](compared-to-core.md)

# Compared with the core integration

Home Assistant ships its own [Proxmox VE integration](https://www.home-assistant.io/integrations/proxmoxve/). This one grew out of it and replaces it when installed, so the fair question is what you get for the extra install. The table is taken from the core integration's source as of **Home Assistant 2026.9** and from this integration's current release; the core integration is being worked on again, so check its documentation if the column looks out of date.

Everything the core integration reads or does is here as well, so switching does not take anything away; entity ids differ, so automations built on the core integration need pointing at the new ones.

Legend: ✅ available · ➖ not available · text where it differs.

## Setup and behaviour

| | Core integration | This integration |
|---|---|---|
| Configuration in the UI, token or password | ✅ | ✅ — the realm as a pick-list, LDAP/AD/OpenID typed in |
| Re-authentication and reconfiguration | ✅ | ✅ |
| What is tracked | Everything the credentials can see, always | Your selection of nodes, guests and storages — or everything, with **Track everything automatically** ([details](behaviour.md#tracking-everything-automatically)) |
| New and removed guests picked up at runtime | ✅ | ✅ with automatic tracking |
| Polling interval | 60 seconds, fixed | 30, 45, 60, 90 or 120 seconds ([details](behaviour.md#how-often-it-polls)) |
| Entity id scheme | Home Assistant's device then name | that, or a prefix and the id before the name ([details](behaviour.md#entity-ids)) |
| Guest renamed in Proxmox | Name follows at the next restart | Name follows at the next poll ([details](behaviour.md#guests-renamed-in-proxmox)) |
| Options after setup | ➖ | ✅ — selection, and an **Advanced configuration** page: physical disks, failed tasks, package updates, polling interval, guest file, backup storage, entity id scheme, cluster credentials |
| Buttons only where the privilege is held | ✅ | ✅ |
| Repairs naming the missing privilege and path | ➖ | ✅ ([details](permissions.md)) |
| Failover to another cluster node when the configured host is down | ➖ | ✅, across a restart of Home Assistant too ([details](behaviour.md#when-the-configured-host-is-down)) |
| Re-login instead of re-authentication after a node was off for hours | ➖ | ✅ ([details](behaviour.md#nodes-that-are-switched-off-for-a-while)) |
| Diagnostics download | ✅ | ✅ |
| Translations | Home Assistant's | Crowdin, currently 13 languages |

## Cluster

| | Core integration | This integration |
|---|---|---|
| Cluster device with nodes online, guests running, CPU and memory across the cluster | ➖ | ✅ |
| Shared storage tracked once instead of once per node | ➖ | ✅ |
| HA status, arm/disarm HA, guests without backup | ➖ | ✅ with optional cluster credentials |
| Ceph health and usage | ➖ | ✅ |

## Nodes

| | Core integration | This integration |
|---|---|---|
| Status, CPU, cores, memory, disk, uptime | ✅ | ✅ |
| Swap, IO delay, load average, version | ➖ | ✅ |
| Last backup, backup status, backup duration | ✅ | ✅ |
| Backup running (for automations that wait) | ➖ | ✅ |
| Package updates as an `update` entity, pending package count | ➖ | ✅ (needs `Sys.Modify`) |
| Failed tasks of the last 24 h | ➖ | ✅ |
| Replication, subscription, certificate expiry | ➖ | ✅ |
| Hardware temperatures, fans, voltages, power | ➖ | ✅ via [PVE-mods](hardware-sensors.md) |
| Physical disks with SMART, temperature, wearout | ➖ | ✅ |
| ZFS pools | ➖ | ✅ |
| Hardware addresses on the device (merges with network integrations) | ➖ | ✅ |

## Virtual machines and containers

| | Core integration | This integration |
|---|---|---|
| Status, CPU, cores, memory, disk, uptime, network in/out | ✅ | ✅ |
| QEMU's finer run states (`paused`, `prelaunch`, `io-error`, …) | ➖ | ✅ |
| CPU as a share of the host | ➖ | ✅ |
| Disk usage from the guest agent | ➖ | ✅ |
| A file read from inside the guest | ➖ | ✅ |
| Snapshot count with names | ➖ | ✅ |
| Guest IP addresses, guest agent answering | ➖ | ✅ |
| Pressure stall information per guest (CPU, IO, memory; waiting and stalled) | ➖ | ✅ ([details](entities.md#virtual-machines-and-containers)) |
| A VM's memory as the host sees it | ➖ | ✅ |
| HA managed | ➖ | ✅ with optional cluster credentials |

## Storage

| | Core integration | This integration |
|---|---|---|
| Used, total, available, percentage | ✅ | ✅ |
| Active, enabled, shared | ✅ | ✅ |
| Which nodes see a shared storage | ➖ | ✅ |

## Actions

| | Core integration | This integration |
|---|---|---|
| Node: reboot, shutdown, start all, stop all, suspend all | ✅ | ✅ |
| Node: Wake on LAN, back up all | ➖ | ✅ |
| VM: start, stop, shutdown, reboot, pause, hibernate, resume, reset, snapshot | ✅ | ✅ |
| Container: start, stop, reboot, snapshot | ✅ | ✅ — plus shutdown and unlock |
| Back up now, per guest | ➖ | ✅ with a [backup storage picked](actions.md#backup-buttons) |
| `proxmoxve.backup` action — guests, nodes or the cluster as target, vzdump's options | ➖ | ✅ |
| Blueprint for a scheduled backup | ➖ | ✅ ([blueprints](https://github.com/dougiteixeira/proxmoxve/blob/main/blueprints/readme.md)) |

## Where the core integration is the better fit

If all you want is to see your guests and start or stop them, the core integration does that without installing anything, follows Home Assistant's release cycle, and needs no thought about what to track. This integration is for everything past that: a cluster, hardware, backups, updates, and an integration that stays up when a node does not.
