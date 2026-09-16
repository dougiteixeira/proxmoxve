# Blueprints

Ready-made automations for the integration. Import one, fill in the fields, done.

## Scheduled backup

Backs up the Proxmox devices you pick at a set time on the days you choose, through the [`proxmoxve.backup` action](../docs/actions.md#the-proxmoxvebackup-action) - the way *Backup now* in the Proxmox interface does, but on a schedule kept in Home Assistant. A VM or container device backs up that guest, a node device everything it hosts, the `Proxmox Cluster` device everything on every node; the node each guest lives on is looked up, so one automation can cover the whole cluster. Nodes with a backup already running are left out rather than queued behind it, and a notification says what started.

The credentials need `VM.Backup` on the guests and `Datastore.AllocateSpace` on the storage, see [Proxmox permissions](../docs/permissions.md).

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https://github.com/dougiteixeira/proxmoxve/blob/main/blueprints/backup_scheduled.yaml)

Or import `https://github.com/dougiteixeira/proxmoxve/blob/main/blueprints/backup_scheduled.yaml` by hand under [Settings > Automations & Scenes > Blueprints](https://my.home-assistant.io/redirect/blueprints/) > Import Blueprint, then create an automation from it.

### Filling in the fields

| Field | What goes in |
|---|---|
| **What to back up** | Proxmox devices from the picker - guests, nodes, the cluster, any mix. Required. |
| **Time**, **Days** | When the run starts. Every day at 03:00 unless you change it. |
| **Storage** | Where the backups go. Empty means the storage picked for the backup buttons in the integration options, or failing that the node's own default. |
| **Mode** | `snapshot` keeps a running guest running, `suspend` pauses it, `stop` shuts it down for the duration. |
| **Compression**, **Notes** | Passed to vzdump as they are; leave them empty for the node's defaults and no notes. |
| **Skip nodes with a backup running** | On by default. vzdump runs one at a time per node; off means a second run queues behind the first. |
| **Notification** | A `notify.*` action to say what started on which node, and which nodes were skipped. |

The runs are started and the automation is done; how they went is on each node's `Last backup` and `Backup status` sensors afterwards, see [Last backup per node](../docs/entities.md#last-backup-per-node).

### The old reload blueprint

Earlier versions shipped a blueprint that reloaded the integration when a Ping sensor saw the host come back, for the case where the integration stayed unavailable - or asked for new credentials - after the host had been offline for a while. The integration recovers from that by itself now: it retries setup until the host answers, logs in again when its ticket has expired, and moves to another node of the cluster when the configured one is down, see [How it behaves](../docs/behaviour.md). The blueprint is gone; an automation created from it can be deleted.
