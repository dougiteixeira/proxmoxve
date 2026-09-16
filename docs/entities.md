[← README](https://github.com/dougiteixeira/proxmoxve#readme) · [Entities](entities.md) · [Actions](actions.md) · [Hardware sensors](hardware-sensors.md) · [Permissions](permissions.md) · [Behaviour](behaviour.md) · [Troubleshooting](troubleshooting.md) · [Compared with core](compared-to-core.md)

# Entities

What the integration reads, by what it belongs to. Entities marked **disabled by default** are enabled per entity, see [Disabled entities](behaviour.md#disabled-entities).

## Cluster

### The cluster at a glance

Every setup gets a `Proxmox Cluster` device with a summary read from the same resource list the integration already polls — no extra privilege:

- **`Nodes online`**, with the total and the names of any offline nodes as attributes.
- **`Virtual machines running`** and **`Containers running`** across the cluster, with the totals as attributes. Templates are not counted.
- **`CPU used`** across the online nodes, weighted by each node's core count — sixteen cores at 50 % and four at 100 % is 60 % of the cluster, not the 75 % a plain average would say.
- **`Memory used percentage`**, and `Memory used` / `Memory total` in bytes disabled by default.

The optional cluster credentials add the HA status and backup coverage to the same device; shared storage hangs there too.

### Cluster HA Administration (Advanced, Optional)

These features let you interact with the Proxmox HA (High Availability) stack, gated behind a **separate, optional** set of credentials:

- **Arm HA / Disarm HA buttons**: cluster-wide equivalents of `ha-manager crm-command arm-ha` / `disarm-ha`, letting you pause HA fencing for planned maintenance (e.g. before/after a node reboot script) and resume it afterwards. Disabled by default even once configured — enable them explicitly like other advanced entities. Disarm always uses `resource-mode=freeze` (HA services stay locked in their current state, no automatic action) rather than `ignore` (which fully suspends HA tracking and allows manual guest management) — the safer of the two, but it means guests aren't freely manageable outside of HA while disarmed. Arm HA resumes normal monitoring from whatever the actual state is at that point; it does not roll anything back.
- **"HA managed" sensor**: a per-VM/CT binary sensor showing whether that guest is currently a Proxmox HA resource.
- **`Guests without backup` sensor**: how many VMs and containers no backup job covers, with the affected guests as an attribute. Zero is the good case. Proxmox filters this to guests the credentials may see, so it reads "not backed up, as far as this user can tell" rather than a cluster-wide truth. Polled hourly — which guests a job covers changes when someone edits a job, not minute to minute.
- **Cluster HA status sensors**: read-only sensors on the `Proxmox Cluster` device, from `GET /cluster/ha/status/current`:
  - `HA armed state` — `armed`, `standby`, `disarming` or `disarmed`, with the active `resource mode` (`freeze`/`ignore`) as an attribute. Arm/Disarm only *queue* a CRM command, so this is the only way to see whether the cluster actually reached the requested state; a disarm run passes through `disarming` until every LRM has released its watchdog. Requires `pve-ha-manager` 5.1.3 or newer — the release that added arm/disarm and the `fencing` status entry it reads; on older clusters the API omits the entry and the sensor is not created.
  - `Quorate` — binary sensor, off when the cluster has lost quorum.
  - `CRM master` — which node currently runs the CRM.
  - `CRM master stale` — binary sensor, on when the CRM master has not refreshed its status for more than 30 s, the same threshold Proxmox itself uses to call a master dead. Proxmox only puts that verdict in a localized display string, so it is recomputed here from the structured timestamp — against the Home Assistant clock, which assumes your HA host and the cluster agree on the time.
  - `CRM master last seen` — the raw timestamp behind the above. **Disabled by default**: the CRM rewrites it every few seconds, so it would record a new state on every poll; enable it if you need the exact value for debugging.
  - `HA resources` and `HA resources in error` — how many resources the HA stack tracks, and how many are currently in `error`, `fence` or `recovery`, with the affected service IDs as an attribute.

  These entities are created during setup from the first successful poll: if HA is configured on the cluster afterwards, reload the integration to pick up the new entities.

> [!CAUTION]
> These need **`Sys.Console`** (arm/disarm) and **`Sys.Audit`** (HA resource list and HA status) on the Proxmox **root path (`/`)** — cluster-wide permissions, well beyond the scoped, per-node/per-VM permissions the rest of this integration recommends. `Sys.Console` in particular is normally associated with shell/console access. Only configure this if you understand and accept that risk.

Because of that, this uses a **separate user or API token** from the main integration credentials, configured via the integration options (`Optional: cluster HA administration (advanced)`). Leave every field empty (the default) to keep these features disabled — the rest of the integration is unaffected either way. A failure to authenticate with these optional credentials only disables these features; it does not break the rest of the integration.

Only relevant if you run a Proxmox **cluster with HA-manager configured** — on a standalone node there are no HA resources to arm/disarm or report on.

> [!IMPORTANT]  
> See the section on Proxmox user permissions [here](permissions.md).

### Ceph health

Clusters running Ceph get a `Ceph health` sensor on the `Proxmox Cluster` device — `ok`, `warning` or `error` — with the failing checks (name, severity, message) as an attribute. **Disabled by default.**

Alongside it, `Ceph used`, `Ceph total` and `Ceph used percentage` report the cluster's usage from the placement group map — the same two totals `ceph -s` prints. **Disabled by default.** The rest of that map, and the monitor and OSD maps, are a different question and a great deal of data to put behind a sensor.

The integration probes `cluster/ceph/status` once during setup and simply does not create the coordinator when Ceph is absent, so clusters without it are not left with something that fails on every update. It needs `Sys.Audit` or `Datastore.Audit` on `/` — the optional cluster credentials already carry that.

### Shared storage, once

Proxmox lists a storage once per node that has it configured, so an NFS export or a Ceph pool a four-node cluster mounts everywhere used to appear four times in Home Assistant with the same numbers. A storage the cluster marks as **shared** is now one device on the `Proxmox Cluster`, tracked as `storage/<name>` instead of `storage/<node>/<name>`. Its figures come from a node that currently reports it available, and the `Node` sensor's `nodes` attribute lists every node that does. Local storage — a directory, an LVM, a ZFS pool — is still per node, because it genuinely is.

If you set the integration up before this change, the switch happens by itself at the next start: of the per-node entries you had picked, the one on the node you configured (or the first you picked) keeps its device, its entities and their history under the new id; the other entries lose their device. Automations that referred to one of the removed entities — `sensor.storage_<other node>_<name>_…` — have to be pointed at the one that stayed. The selection in the integration options shows shared storage once from now on, marked *(shared)*.

## Nodes

### Status sensors (nodes, VMs and containers)

Every node, VM and container has a `Status` sensor. They are proper enum sensors: the states are translated, usable in the history graph, and offered as a pick-list in automation conditions. A VM reports QEMU's finer run state where there is one — `paused`, `prelaunch`, `io-error`, `guest-panicked`, a migration in progress — and `running`/`stopped`/`suspended` otherwise; a container is `running` or `stopped`; a node is `online`, `offline` or `unknown`.

A state this integration has never heard of reads as unknown rather than breaking the sensor, so a future QEMU release cannot take the entity down.

### Node figures

Beyond CPU, memory, swap and disk, each node reports:

- **`IO delay`** — the share of time the CPUs spent waiting for I/O, what the node summary in Proxmox shows as IO delay and the figure to watch when storage is the bottleneck.
- **`Load average 1 min`**, and `5 min` / `15 min` disabled by default.
- **`Version`** — the Proxmox VE version, as a diagnostic sensor rather than only on the device page.
- **`CPUs`** — the node's logical CPU count, diagnostic, disabled by default.

The node's device also carries the hardware addresses of its physical ports, read from the MAC-based interface names Proxmox lists, so Home Assistant can merge it with what a network integration sees of the same machine.

### Package updates

Each node gets a `Software update` entity of Home Assistant's `update` type, so pending package upgrades show up under Settings → Updates and in the update card, next to everything else that wants upgrading. It behaves exactly like the entity in the Home Assistant core integration: the installed version is the node's Proxmox VE release, the latest version is the highest version among the installed release and Proxmox's own pending packages, written as `<version>-p<proxmox packages>-d<other packages>` so it changes whenever the set of pending packages does, and the release notes say how many packages are pending and link to the node.

It reads `GET /nodes/{node}/apt/update`, which needs `Sys.Modify` on the node. Without that privilege nothing about package updates is created — no entity, no count sensor, and no repair asking for a permission a read-only setup deliberately does not hold. Grant it and reload the integration to get them. There is no install button: the API offers no way to run the upgrade, and a dist-upgrade of a hypervisor is not something to start from a dashboard anyway.

The older `Total updates` sensor and `Updates packages` binary sensor stay as they are.

### Last backup per node

Each node reports its most recent finished backup run, read from the node's task log (`GET /nodes/{node}/tasks?typefilter=vzdump`). All three are diagnostic and **disabled by default**, as in the Home Assistant core integration:

- `Last backup` — when the run finished, with the run's verdict, the guests it covered and the user that started it as attributes.
- `Backup status` — a problem binary sensor, on when the run's verdict was anything but `OK`. That includes `job errors`, where some guests were backed up and some were not.
- `Backup duration` — how long the run took.

Only finished runs count for those three. A run still in progress has no end time and no verdict yet, and reporting it there would make every backup look like a failure while it runs. Nodes that have never run a backup get none of them. Polled once a minute; needs `Sys.Audit` on the node to see runs other users started.

A fourth entity, **`Backup running`**, is on while a `vzdump` run is in progress on the node — with its start and the guests it covers as attributes — and exists for every node, on by default. That is what an automation waits for before shutting a node down.

For the other direction - which guests no backup job covers at all - see the `Guests without backup` sensor under [Cluster HA Administration](entities.md#cluster-ha-administration-advanced-optional).

### Failed task monitoring

The integration provides sensors that monitor failed tasks on your Proxmox nodes over the last 24 hours. These sensors offer:

- **Failed Task Count**: Shows the number of failed tasks per node
- **Recent Failure Details**: Displays information about recent failed tasks including:
  - Task type (backup, migration, etc.)
  - Start and end timestamps (in your local timezone)
  - Task status
- **Configurable**: Can be enabled or disabled during integration setup or via integration options
- **Automatic Updates**: Refreshes every 5 minutes to provide up-to-date information

The failed task sensors help you monitor the health of your Proxmox operations and quickly identify when automated tasks encounter issues.

### Replication

For nodes running ZFS replication, two entities per node, both **disabled by default** and only created when that node actually has replication jobs:

- `Replication failing` — a problem binary sensor, on when any active job has failures, with the affected jobs (id, guest, target, failure count, error) as an attribute.
- `Replication last sync` — the **oldest** successful sync across the node's active jobs. The oldest rather than the newest on purpose: the newest would hide a job that stopped replicating days ago, which is exactly the case worth seeing.

Jobs somebody disabled are counted but never raise the alarm or hold back the timestamp.

Proxmox filters this to guests the credentials may audit (`VM.Audit`), so no extra permissions are needed beyond what tracking those guests already requires.

### Subscription

Each node gets a `Subscription` sensor — `active`, `expired`, `invalid`, `suspended`, `new` or `none` — with the level, product name and next due date as attributes. **Disabled by default**: most installations run without a subscription, where it reads "none" forever and is worth having only once there is one.

The subscription key, the server ID and the response signature are deliberately not exposed. They identify the machine and the subscription, and would otherwise end up in a state attribute and in every diagnostics dump.

Like the certificate sensor, this needs no permissions beyond being able to log in, and is polled hourly.

### Certificate expiry

Each node gets a `Certificate expires` sensor, **disabled by default** — enable it like other [disabled entities](behaviour.md#disabled-entities). It reports the expiry of the certificate that actually serves the API and web interface: `pveproxy-ssl.pem` if you replaced it with your own or an ACME one, otherwise the `pve-ssl.pem` the cluster's own CA issued. The file, subject and issuer are attributes.

It is off by default because most installations run on the cluster CA's self-signed certificate, where an expiry two years out is not something to watch. It earns its place once you put a real certificate on the node — that is what tends to expire unnoticed.

The cluster CA itself (`pve-root-ca.pem`) is deliberately not reported: it is valid for ten years and its expiry is not something you act on.

This needs no permissions beyond being able to log in, and it is polled once an hour rather than once a minute, since certificates only change when someone replaces them.

## Virtual machines and containers

### CPU per guest

A guest's `CPU used` is relative to its own cores: a two-core guest at 100 % and a twelve-core one at 100 % read the same while costing the host very different amounts. The sensor carries the guest's core count as an attribute, and a second sensor, **`CPU used of host`** (disabled by default), scales the guest's usage by its cores over the node's — the figure the Proxmox summary shows next to each guest.

A container that is not running reports its disk usage as *unknown* rather than 0 % used and 100 % free: Proxmox cannot look inside a stopped container and reports `disk: 0`, but the data is still on the volume. Memory and swap stay at 0 % for a stopped guest, because those really are zero.

### Guest file content sensor

For QEMU virtual machines with the [QEMU Guest Agent](https://pve.proxmox.com/wiki/Qemu-guest-agent) installed and running, you can configure an absolute file path (in the integration options) that will be read from inside each tracked VM and exposed as a sensor.

- Configured once for all tracked QEMU VMs, via the integration options (`Guest file path to monitor`). Leave empty to disable (default).
- Only VMs where the file can actually be read (guest agent running, file exists and is accessible) get the sensor; it is silently skipped otherwise.
- Content is capped at 4 KiB per read; the sensor state is further truncated to 255 characters (Home Assistant's state length limit), with the full (capped) content available as the `guest_file_content` attribute.
- QEMU only — LXC containers have no equivalent guest-agent file-read API.

## Storage

### Storage state

Besides its capacity sensors, each selected storage gets three diagnostic binary sensors read from the node's own storage list (`GET /nodes/{node}/storage`), the same three as in the Home Assistant core integration:

- `Storage active` — whether the node can currently reach the storage, which is what changes when an NFS server goes away or a USB disk is unplugged.
- `Storage enabled` and `Storage shared` — how the storage is configured.

They need the same `Datastore.Audit` on the storage as the capacity sensors. When that list cannot be read, the entities are not created rather than left permanently off.

Physical disks, ZFS pools and hardware temperatures are on their own page: [Hardware sensors](hardware-sensors.md).
