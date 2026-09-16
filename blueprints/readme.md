# Blueprints

Ready-made automations for the integration. Import one, fill in the fields, done.

## Scheduled backup

Starts a backup run on a node at a set time on the days you pick, through the [`proxmoxve.backup` action](../docs/actions.md#the-proxmoxvebackup-action) - the way *Backup now* in the Proxmox interface does, but on a schedule kept in Home Assistant. Name the guests to back up or leave the list empty for everything the node hosts; pick storage, mode and compression; optionally have the run skipped while the node's `Backup running` sensor is on, and get a notification with the task id when it starts.

The credentials need `VM.Backup` on the guests and `Datastore.AllocateSpace` on the storage, see [Proxmox permissions](../docs/permissions.md).

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https://github.com/dougiteixeira/proxmoxve/blob/main/blueprints/backup_scheduled.yaml)

Or import `https://github.com/dougiteixeira/proxmoxve/blob/main/blueprints/backup_scheduled.yaml` by hand under [Settings > Automations & Scenes > Blueprints](https://my.home-assistant.io/redirect/blueprints/) > Import Blueprint. Then create an automation from it: the node's name as Proxmox shows it, the storage, the time, the days, and - optionally - the guests, the node's `Backup running` sensor and a `notify.*` action.

### Filling in the fields

| Field | What goes in |
|---|---|
| **Node** | The node's name as Proxmox shows it, e.g. `pve`. Required. |
| **Storage** | The storage the backup is written to; it has to accept backups. Required. |
| **Time**, **Days** | When the run starts. Every day at 03:00 unless you change it. |
| **Guests** | The VM and container ids as a list, `[100, 101]`. Empty means everything the node hosts. |
| **Mode** | `snapshot` keeps a running guest running, `suspend` pauses it, `stop` shuts it down for the duration. |
| **Compression**, **Notes** | Passed to vzdump as they are; leave them empty for the node's defaults and no notes. |
| **Backup running sensor** | The node's `Backup running` sensor. While it is on the run is skipped, not queued. |
| **Notification** | A `notify.*` action to say that the run started, with the task id. |

The run is started and the automation is done; how it went is on the node's `Last backup` and `Backup status` sensors afterwards, see [Last backup per node](../docs/entities.md#last-backup-per-node).

### The old reload blueprint

Earlier versions shipped a blueprint that reloaded the integration when a Ping sensor saw the host come back, for the case where the integration stayed unavailable - or asked for new credentials - after the host had been offline for a while. The integration recovers from that by itself now: it retries setup until the host answers, logs in again when its ticket has expired, and moves to another node of the cluster when the configured one is down, see [How it behaves](../docs/behaviour.md). The blueprint is gone; an automation created from it can be deleted.
