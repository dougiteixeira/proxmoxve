[← README](https://github.com/dougiteixeira/proxmoxve#readme) · [Entities](entities.md) · [Actions](actions.md) · [Hardware sensors](hardware-sensors.md) · [Permissions](permissions.md) · [Behaviour](behaviour.md) · [Troubleshooting](troubleshooting.md) · [Compared with core](compared-to-core.md)

# How it behaves

## Tracking everything automatically

By default the integration tracks exactly the nodes, guests and storages you picked during setup, and a new VM shows up only once you add it in the integration options. The option **Track everything automatically** (in the same options step) turns that around: everything the credentials can see is tracked, and the cluster is followed from then on — a guest that is created is picked up within a minute, a guest that is deleted is dropped together with its device, and the same goes for nodes and storages. Templates are never tracked, because nothing on a template ever changes.

The selection lists are ignored while this is on, but they are not changed: what you picked stays stored exactly as it was, and switching the option off again brings that selection back at the next reload. Under the hood the integration brings its configuration in line with `GET /cluster/resources` at setup and keeps comparing once a minute. Like the Home Assistant core integration it then acts on the difference in place: a new node, guest or storage gets its coordinators, device and entities right away, a vanished one loses them — nothing is reloaded and nothing else goes unavailable.

Because `cluster/resources` only lists what the credentials may audit, "everything" means everything this user can see. A guest the user has no `VM.Audit` on is simply not there.

## When the configured host is down

Every request goes through the one host you configured; its `pveproxy` forwards to the other nodes. Until now that host being down took the whole cluster out of Home Assistant, however many nodes were still running.

The integration now asks `cluster/status` at setup what address every node answers on, and when the configured host stops answering it moves to the next node that does — logged as a warning — and keeps polling there. Nothing needs to be configured, and the configured host stays the one shown and the one every start goes to first.

Those addresses are kept in the config entry, so a restart while the configured node is down finds them: the very first request of a setup can then go to another node, and the entry loads instead of waiting for the node to come back. They are refreshed whenever the cluster can be asked, and a reload that cannot read `cluster/status` leaves the last ones standing. Like the host itself, they are redacted from the diagnostics download.

Two limits. The addresses in `cluster/status` are the ones the nodes joined the cluster on; if your cluster runs corosync on a separate network, Home Assistant cannot reach them and the fallback finds nothing — which leaves things exactly as they were before. And with **Verify SSL certificate** on, a fallback node has to present a certificate valid for that address, which per-node certificates usually are not.

## How often it polls

Nodes, guests, storage, backups, the cluster summary and discovery are read every **60 seconds** unless you pick another interval — 30, 45, 90 or 120 seconds — under *Advanced configuration*. Proxmox's own `pvestatd` refreshes guest figures about every ten seconds, so anything faster than 30 would mostly read the same numbers again. Certificates, subscriptions and Ceph are read hourly and the failed-task scan every five minutes, whatever the interval. The cluster's resource list, which every guest and storage coordinator needs, is read once per polling burst and shared — not once per entity. Any single coordinator can still be refreshed on demand with `homeassistant.update_entity` on one of its entities.

## Nodes that are switched off for a while

With password authentication, a node that is off for longer than two hours used to demand new credentials when it came back: the login ticket had expired and its renewal was refused exactly like a wrong password. The integration now logs in again with the stored password before asking for anything, so a node that is off overnight simply resumes in the morning. A host that answers during boot but is not issuing tickets yet leaves setup retrying rather than asking for credentials. Tokens never had this problem; they do not expire.

## Entity ids

Home Assistant builds an entity id from the device name and the entity name: `sensor.qemu_docmost_109_cpu_used`, `sensor.node_pve_cpu_used`, `binary_sensor.storage_local_storage_active`. That puts the kind first and the guest's id last, and nothing in front by which a recorder filter or a search could catch everything of this integration. That is the **standard** scheme. The option **Entity id scheme** — chosen when you set the integration up, changeable in the integration options; setups from before the option are on standard — offers an **extended** scheme with a common prefix first and the id before the name:

| Device | Entity id |
|---|---|
| Cluster | `<prefix>_cluster_<item>` |
| Node | `<prefix>_node_<node>_<item>` |
| VM / container | `<prefix>_qemu_<vmid>_<name>_<item>` / `<prefix>_lxc_<vmid>_<name>_<item>` |
| Storage | `<prefix>_storage_<node>_<storage>_<item>`, shared: `<prefix>_storage_<storage>_<item>` |
| Physical disk | `<prefix>_disk_<node>_<model>_<item>` |
| ZFS pool | `<prefix>_zfs_<node>_<pool>_<item>` |

`<prefix>` is `pve` unless you type another into **Prefix for the extended scheme**; `<item>` is the entity's translation key (`cpu_used`, `status_raw`, `backup_running`), so the ids read the same whatever language Home Assistant runs in. Sorted, a list of guests is now in vmid order; `pve_` in front of everything makes a recorder `include`/`exclude` a one-liner.

**Nothing changes for entities that exist.** The scheme is a suggestion Home Assistant takes when it registers an entity for the first time; an entity that already has an id keeps it, whatever the option says, and there is no bulk rename — renaming ids would break every automation, dashboard and history that refers to them. Choose extended when you set the integration up and every entity gets those ids; switch a running setup to extended and only entities created from then on do. To move a running install over, remove the integration and add it again (history is lost), or rename the entities you care about by hand.

## Guests renamed in Proxmox

A guest renamed in Proxmox keeps its id, so it stays the same device here — only its name was stale: it was written when the device was created and then never again, which left a container you create and name afterwards showing `LXC CT516 (516)` until the next restart. The name now follows at the next poll, and with it the names of its entities, because Home Assistant builds those from the device name.

A name you gave the device yourself in Home Assistant is untouched: Home Assistant keeps it separately and shows it instead, whatever Proxmox reports. Entity ids keep theirs as well — see [Entity ids](#entity-ids) above for why nothing is renamed in bulk.

## Disabled entities

Some entities are disabled by default (including control buttons), see below how to enable them.

 <details><summary>A step by step to enable entities</summary>
  
   1) Go to the page for the device you want to enable the button (or sensor).

      ![image](https://github.com/dougiteixeira/proxmoxve/assets/31328123/4e3f9b7d-e935-4fc5-bdd3-3329ef9b90a8)
   
   2) Click +x entities not show

      ![image](https://github.com/dougiteixeira/proxmoxve/assets/31328123/0240d2ed-efac-4c59-9def-e721a44dde90)
   
   3) Click on the entity you want to enable and click on settings (on the gear icon):

      ![image](https://github.com/dougiteixeira/proxmoxve/assets/31328123/e1bd2fb2-6fb5-4919-88c1-8056b7435f87)
   
   4) Click the Enable button at the top of the dialog:

      ![image](https://github.com/dougiteixeira/proxmoxve/assets/31328123/1a8205e4-a779-4a01-922d-5d147e8e5766)
   
   5) Wait a while (approximately 30 seconds) for the entity to be enabled. If you don't want to wait, just reload the configuration entry on the integration page.

      ![image](https://github.com/dougiteixeira/proxmoxve/assets/31328123/33edd547-8c55-44eb-b0b9-5036317bf077)
   
   For the entity to appear enabled on the device page, it may be necessary to refresh the page.
   </details>

## Features I cannot test myself

My own cluster does not use every feature this integration reads, so some
code paths have only ever run against the Proxmox API definitions and
invented test fixtures — never against a live setup. They are listed here
honestly rather than presented as equally proven:

| Feature | What is untested |
|---|---|
| **Ceph** | Everything. I run no Ceph, so the endpoint is absent here. The health values come from Ceph itself rather than a Proxmox schema, since `cluster/ceph/status` hands `ceph -s` through unchanged. |
| **Replication** | Only the failure path. A healthy job has been confirmed against a live cluster; what a job reports once it starts failing — `fail_count`, `error` — has not. |
| **Subscription** | Only the `none` state is confirmed. I hold no subscription, so `active`, `expired`, `invalid` and `suspended` — and the level, product and due date attributes — have never been seen from a real response. |

**If you run any of these, I would genuinely like to hear whether they work.**
An issue saying "replication sensor shows the wrong thing" — ideally with the
output of `pvesh get /nodes/<node>/replication --output-format json`, with
anything sensitive removed — is more useful than it might feel, because I
cannot produce that response myself.
