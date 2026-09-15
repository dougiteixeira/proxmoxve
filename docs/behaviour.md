[← README](https://github.com/dougiteixeira/proxmoxve#readme) · [Entities](entities.md) · [Actions](actions.md) · [Hardware sensors](hardware-sensors.md) · [Permissions](permissions.md) · [Behaviour](behaviour.md) · [Troubleshooting](troubleshooting.md)

# How it behaves

## Tracking everything automatically

By default the integration tracks exactly the nodes, guests and storages you picked during setup, and a new VM shows up only once you add it in the integration options. The option **Track everything automatically** (in the same options step) turns that around: everything the credentials can see is tracked, and the cluster is followed from then on — a guest that is created is picked up within a minute, a guest that is deleted is dropped together with its device, and the same goes for nodes and storages. Templates are never tracked, because nothing on a template ever changes.

The selection lists are ignored while this is on, but they are not changed: what you picked stays stored exactly as it was, and switching the option off again brings that selection back at the next reload. Under the hood the integration brings its configuration in line with `GET /cluster/resources` at setup and keeps comparing once a minute. Like the Home Assistant core integration it then acts on the difference in place: a new node, guest or storage gets its coordinators, device and entities right away, a vanished one loses them — nothing is reloaded and nothing else goes unavailable.

Because `cluster/resources` only lists what the credentials may audit, "everything" means everything this user can see. A guest the user has no `VM.Audit` on is simply not there.

## When the configured host is down

Every request goes through the one host you configured; its `pveproxy` forwards to the other nodes. Until now that host being down took the whole cluster out of Home Assistant, however many nodes were still running.

The integration now asks `cluster/status` at setup what address every node answers on, and when the configured host stops answering it moves to the next node that does — logged as a warning — and keeps polling there. Nothing needs to be configured, and nothing is written to the entry: the configured host stays the one shown, and the next reload starts there again.

Two limits. The addresses in `cluster/status` are the ones the nodes joined the cluster on; if your cluster runs corosync on a separate network, Home Assistant cannot reach them and the fallback finds nothing — which leaves things exactly as they were before. And with **Verify SSL certificate** on, a fallback node has to present a certificate valid for that address, which per-node certificates usually are not.

## Nodes that are switched off for a while

With password authentication, a node that is off for longer than two hours used to demand new credentials when it came back: the login ticket had expired and its renewal was refused exactly like a wrong password. The integration now logs in again with the stored password before asking for anything, so a node that is off overnight simply resumes in the morning. A host that answers during boot but is not issuing tickets yet leaves setup retrying rather than asking for credentials. Tokens never had this problem; they do not expire.

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
