[← README](https://github.com/dougiteixeira/proxmoxve#readme) · [Entities](entities.md) · [Actions](actions.md) · [Hardware sensors](hardware-sensors.md) · [Permissions](permissions.md) · [Behaviour](behaviour.md) · [Troubleshooting](troubleshooting.md)

# Actions

## Buttons

Every VM and container gets `Start`, `Stop`, `Shutdown`, `Reboot`, `Suspend`, `Resume`, `Hibernate`, `Reset`, `Unlock`, `Create snapshot` and, with a [backup storage picked](#backup-buttons), `Back up now`. Every node gets `Start all`, `Stop all`, `Suspend all`, `Shutdown`, `Reboot`, `Wake on LAN` and `Back up all`. The cluster device gets `Arm HA` and `Disarm HA` with the [optional cluster credentials](entities.md#cluster-ha-administration-advanced-optional).

All of them are **disabled by default** — a dashboard should not offer a stop button nobody asked for — and are enabled per entity, see [Disabled entities](behaviour.md#disabled-entities). And every one of them exists only where the credentials hold the privilege it needs, see [Permissions](permissions.md).

> [!NOTE]
> The `Create snapshot` button takes a disk-only snapshot (no RAM state) named `homeassistant_<date>_<time>` in your local time, described as "Created by Home Assistant" so it is recognisable in the snapshot list later. It needs `VM.Snapshot` on the guest; snapshots of a running container additionally need a storage that supports them.

> [!NOTE]
> The Wake on LAN button only works if the configured node is in a cluster of two or more nodes. If you want to use WOL on a single Node, use the official `Wake-On-Lan` integration.

## Backup buttons

For a dashboard there are buttons as well: **`Back up now`** on every VM and container, **`Back up all`** on every node. A button cannot ask where to write, so they need the option **Backup storage for the backup buttons** in the integration options — a pick-list of the storages that accept backups, any other name can be typed in. Without a storage picked there are no buttons at all, since `vzdump` would otherwise dump into the node's local directory; and like every other button they exist only where the credentials hold the privilege, `VM.Backup` here. Both run in snapshot mode. Off by default like the other buttons that change things.

## The `proxmoxve.backup` action

The action **`proxmoxve.backup`** starts a backup run on a node, the way *Backup now* in the Proxmox interface does: name the guests (`vmid`), or turn on `all` for everything the node hosts; pick the `storage`, the `mode` (`snapshot`, `suspend`, `stop`) and the `compress`ion, or leave them to the node's defaults; `notes` sets the backup's notes template (`{{guestname}}`, `{{vmid}}`, `{{node}}`, `{{cluster}}`) and needs a `storage` alongside it, as vzdump does. It returns the task id (`upid`), and the node's `Backup running` sensor turns on with the next poll.

```yaml
action: proxmoxve.backup
data:
  node: pve
  vmid: [100, 101]
  storage: backups
  mode: snapshot
```

The credentials need `VM.Backup` on each guest and `Datastore.AllocateSpace` on the storage; Proxmox's refusal names what is missing, and the action passes that message on.

For a backup on a schedule without writing the automation yourself there is a [blueprint](https://github.com/dougiteixeira/proxmoxve/blob/main/blueprints/readme.md#scheduled-backup): time, days, node, storage, the guests or everything, skipped while another run is in progress, with a notification when it starts.
