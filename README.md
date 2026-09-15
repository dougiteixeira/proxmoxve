# Proxmox VE Custom Integration for Home Assistant
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://github.com/user-attachments/assets/5b5a8c5b-885b-4233-a858-2e78b97d8c74">
  <img src="https://github.com/dougiteixeira/proxmoxve/assets/31328123/dfec7426-852d-41ea-b6c1-9bfd8cd1e8a8">
</picture>


[Proxmox VE](https://www.proxmox.com/en/) is an open-source server virtualization environment. This integration allows you to poll various data and controls from your instance.

This integration started as improvements to the [Home Assistant core's Proxmox VE integration](https://www.home-assistant.io/integrations/proxmoxve/), but I'm new to programming and couldn't meet all of the core's code requirements. So I decided to keep it as a custom integration. Therefore, when installing this, the core integration will be replaced.

After configuring this integration, the following information is available:

 - Binary sensor entities with the status of node and selected virtual machines/containers.
 - Sensor entities of the selected node and virtual machines/containers. Some sensors are created disabled by default, you can enable them by accessing the entity's configuration.
 - **Failed task monitoring sensors** that track failed tasks from the last 24 hours on selected nodes, showing the count of failures and details about recent failed tasks.
 - Entities button to control selected virtual machines/containers (see about Proxmox user permissions below). By default, the entities buttons to control virtual machines/containers are created disabled, [see how to enable them here](#disabled-entities).

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

### Starting a backup

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

### Backup buttons

For a dashboard there are buttons as well: **`Back up now`** on every VM and container, **`Back up all`** on every node. A button cannot ask where to write, so they need the option **Backup storage for the backup buttons** in the integration options — a pick-list of the storages that accept backups, any other name can be typed in. Without a storage picked there are no buttons at all, since `vzdump` would otherwise dump into the node's local directory; and like every other button they exist only where the credentials hold the privilege, `VM.Backup` here. Both run in snapshot mode. Off by default like the other buttons that change things.

For the other direction - which guests no backup job covers at all - see the `Guests without backup` sensor under [Cluster HA Administration](#cluster-ha-administration-advanced-optional).

### Failed Task Monitoring

The integration provides sensors that monitor failed tasks on your Proxmox nodes over the last 24 hours. These sensors offer:

- **Failed Task Count**: Shows the number of failed tasks per node
- **Recent Failure Details**: Displays information about recent failed tasks including:
  - Task type (backup, migration, etc.)
  - Start and end timestamps (in your local timezone)
  - Task status
- **Configurable**: Can be enabled or disabled during integration setup or via integration options
- **Automatic Updates**: Refreshes every 5 minutes to provide up-to-date information

The failed task sensors help you monitor the health of your Proxmox operations and quickly identify when automated tasks encounter issues.

### Status sensors

Every node, VM and container has a `Status` sensor. They are proper enum sensors: the states are translated, usable in the history graph, and offered as a pick-list in automation conditions. A VM reports QEMU's finer run state where there is one — `paused`, `prelaunch`, `io-error`, `guest-panicked`, a migration in progress — and `running`/`stopped`/`suspended` otherwise; a container is `running` or `stopped`; a node is `online`, `offline` or `unknown`.

A state this integration has never heard of reads as unknown rather than breaking the sensor, so a future QEMU release cannot take the entity down.

### Node figures

Beyond CPU, memory, swap and disk, each node reports:

- **`IO delay`** — the share of time the CPUs spent waiting for I/O, what the node summary in Proxmox shows as IO delay and the figure to watch when storage is the bottleneck.
- **`Load average 1 min`**, and `5 min` / `15 min` disabled by default.
- **`Version`** — the Proxmox VE version, as a diagnostic sensor rather than only on the device page.
- **`CPUs`** — the node's logical CPU count, diagnostic, disabled by default.

The node's device also carries the hardware addresses of its physical ports, read from the MAC-based interface names Proxmox lists, so Home Assistant can merge it with what a network integration sees of the same machine.

### CPU per guest

A guest's `CPU used` is relative to its own cores: a two-core guest at 100 % and a twelve-core one at 100 % read the same while costing the host very different amounts. The sensor carries the guest's core count as an attribute, and a second sensor, **`CPU used of host`** (disabled by default), scales the guest's usage by its cores over the node's — the figure the Proxmox summary shows next to each guest.

A container that is not running reports its disk usage as *unknown* rather than 0 % used and 100 % free: Proxmox cannot look inside a stopped container and reports `disk: 0`, but the data is still on the volume. Memory and swap stay at 0 % for a stopped guest, because those really are zero.

### Storage state

Besides its capacity sensors, each selected storage gets three diagnostic binary sensors read from the node's own storage list (`GET /nodes/{node}/storage`), the same three as in the Home Assistant core integration:

- `Storage active` — whether the node can currently reach the storage, which is what changes when an NFS server goes away or a USB disk is unplugged.
- `Storage enabled` and `Storage shared` — how the storage is configured.

They need the same `Datastore.Audit` on the storage as the capacity sensors. When that list cannot be read, the entities are not created rather than left permanently off.

### Shared storage, once

Proxmox lists a storage once per node that has it configured, so an NFS export or a Ceph pool a four-node cluster mounts everywhere used to appear four times in Home Assistant with the same numbers. A storage the cluster marks as **shared** is now one device on the `Proxmox Cluster`, tracked as `storage/<name>` instead of `storage/<node>/<name>`. Its figures come from a node that currently reports it available, and the `Node` sensor's `nodes` attribute lists every node that does. Local storage — a directory, an LVM, a ZFS pool — is still per node, because it genuinely is.

If you set the integration up before this change, the switch happens by itself at the next start: of the per-node entries you had picked, the one on the node you configured (or the first you picked) keeps its device, its entities and their history under the new id; the other entries lose their device. Automations that referred to one of the removed entities — `sensor.storage_<other node>_<name>_…` — have to be pointed at the one that stayed. The selection in the integration options shows shared storage once from now on, marked *(shared)*.

### Hardware Sensors

The integration automatically discovers and exposes hardware temperature, voltage, power, current, and fan speed sensors from Proxmox VE hosts via `lm-sensors`.

#### Prerequisites

On each Proxmox VE host, install `lm-sensors` and [PVE-mods](https://github.com/Meliox/PVE-mods), either variant:

- **v2 (`node_info`, current)** — installed via its Debian package/configure wizard. Exposes sensor data under a `PveMod_JsonSensorInfo` field (temperature only; its separate GPU/UPS/system-info fields aren't read by this integration). See the PVE-mods README for install instructions.
- **Legacy script (`pve-mod-gui-sensors.sh`)** — still supported, exposes a `sensorsOutput` field:
  ```bash
  apt-get install lm-sensors
  wget https://raw.githubusercontent.com/Meliox/PVE-mods/main/legacy-scripts/pve-mod-gui-sensors.sh
  bash pve-mod-gui-sensors.sh install
  ```

Both are auto-detected — whichever one is installed and enabled for temperature sensors is used, no configuration needed on the integration side. Compatible with Proxmox VE 9.0-9.2 per the PVE-mods README; check there for current install instructions if paths change again.

This modifies the Proxmox VE API to inject `sensors -j` output into the `GET /nodes/{node}/status` response. No additional API calls are made by the integration.

#### When readings come and go

PVE-mods v2 collects on demand rather than continuously. A worker started by `pveproxy` runs `sensors`, enriches the output with drive and CPU names, and writes it to `/run/pveproxy/pve-mod/sensors.json`; the API handler reads that file back when you ask for a node's status. After ten seconds without a request the worker stops its collectors and removes the whole directory again.

So a poll that arrives while nothing is warm gets the field **present but empty**, and every hardware sensor on that node would drop to *unknown*. The data is there a second or two later, once that same request has woken the worker. This is how PVE-mods is meant to work — a missing directory is not a fault, and there is nothing to repair on the host.

The ten seconds are hard-wired: `collector_timeout` lives in the package's `PVE/PVEMod/Config.pm` and is not among the sections `pve-mod.conf` can override, so setting it there is accepted and silently ignored.

The integration therefore keeps the previous readings for up to ten minutes when a poll brings none, which covers the gap without polling the API more often. Past ten minutes it reports nothing, because by then the data really is gone rather than late — PVE-mods removed, the module unloaded, `lm-sensors` broken.

If your hardware sensors stay unknown for longer than that, check the source rather than the integration — ask twice, a few seconds apart, so the first request wakes the collector:

```bash
pvesh get /nodes/$(hostname)/status --output-format json | grep -c PveMod_JsonSensorInfo
sleep 3
ls -l /run/pveproxy/pve-mod/sensors.json
journalctl -u pveproxy --since today | grep -i pve-mod
```

#### Physical disks and SMART

The per-disk temperature, power-on hours, power cycles, wearout and health come from `nodes/{node}/disks/smart`. Proxmox hands that out in two shapes — smartctl's numbered attributes for SATA drives, and its text log for NVMe and SAS drives — and both are read, including the SAS labels (`Current Drive Temperature`, `Accumulated start-stop cycles`, `Accumulated power on time, hours:minutes`) an enterprise drive behind an expander uses. A value the drive does not have, such as a virtual NVMe reporting its temperature as `-`, is left out; it no longer takes the whole disk offline.

#### Supported Hardware

| Chip / Driver | Device Type | Examples |
|---------------|-------------|----------|
| `k10temp`, `k8temp`, `coretemp`, `peci-cputemp` | CPU | Tctl, Tdie, Package temperature |
| `amdgpu`, `i915`, `nvidia_gpu` | GPU | Core voltage, hotspot temperature, power, clock |
| `nvme`, `drivetemp` | Storage | NVMe/Drive temperature |
| `jc42`, `spd5118`, `sodimm` | Memory | DIMM temperature |
| `nct6775`, `it87`, `w83627` | Motherboard | System/CPU/Aux temperature |
| `mlx5`, `igb`, `ixgbe` | NIC | NIC temperature, power |
| `pmbus`, `corsair`, `lm25066` | PSU | Power supply temperature, power |
| `emc2305`, `pwm-fan`, `max31785` | Cooling | Fan speed (RPM) |

#### Auto-classification

Each sensor is automatically classified:

- **Names** mapped from known labels (e.g. `Tctl` → `CPU control temperature`, `edge` → `GPU hotspot`)
- **Units** inferred from sensor name patterns (temperature in °C, voltage in V, power in W, frequency in MHz, current in A, fan speed in RPM)
- **Device classes** set accordingly (`temperature`, `voltage`, `power`, `frequency`, `current`)
- **Icons** assigned per device type

Sensors are created under the corresponding Node device in Home Assistant and are marked as `diagnostic`.

### Guest File Content Sensor

For QEMU virtual machines with the [QEMU Guest Agent](https://pve.proxmox.com/wiki/Qemu-guest-agent) installed and running, you can configure an absolute file path (in the integration options) that will be read from inside each tracked VM and exposed as a sensor.

- Configured once for all tracked QEMU VMs, via the integration options (`Guest file path to monitor`). Leave empty to disable (default).
- Only VMs where the file can actually be read (guest agent running, file exists and is accessible) get the sensor; it is silently skipped otherwise.
- Content is capped at 4 KiB per read; the sensor state is further truncated to 255 characters (Home Assistant's state length limit), with the full (capped) content available as the `guest_file_content` attribute.
- QEMU only — LXC containers have no equivalent guest-agent file-read API.

### The cluster at a glance

Every setup gets a `Proxmox Cluster` device with a summary read from the same resource list the integration already polls — no extra privilege:

- **`Nodes online`**, with the total and the names of any offline nodes as attributes.
- **`Virtual machines running`** and **`Containers running`** across the cluster, with the totals as attributes. Templates are not counted.
- **`CPU used`** across the online nodes, weighted by each node's core count — sixteen cores at 50 % and four at 100 % is 60 % of the cluster, not the 75 % a plain average would say.
- **`Memory used percentage`**, and `Memory used` / `Memory total` in bytes disabled by default.

The optional cluster credentials add the HA status and backup coverage to the same device; shared storage hangs there too.

### Ceph health

Clusters running Ceph get a `Ceph health` sensor on the `Proxmox Cluster` device — `ok`, `warning` or `error` — with the failing checks (name, severity, message) as an attribute. **Disabled by default.**

Alongside it, `Ceph used`, `Ceph total` and `Ceph used percentage` report the cluster's usage from the placement group map — the same two totals `ceph -s` prints. **Disabled by default.** The rest of that map, and the monitor and OSD maps, are a different question and a great deal of data to put behind a sensor.

The integration probes `cluster/ceph/status` once during setup and simply does not create the coordinator when Ceph is absent, so clusters without it are not left with something that fails on every update. It needs `Sys.Audit` or `Datastore.Audit` on `/` — the optional cluster credentials already carry that.

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

Each node gets a `Certificate expires` sensor, **disabled by default** — enable it like other [disabled entities](#disabled-entities). It reports the expiry of the certificate that actually serves the API and web interface: `pveproxy-ssl.pem` if you replaced it with your own or an ACME one, otherwise the `pve-ssl.pem` the cluster's own CA issued. The file, subject and issuer are attributes.

It is off by default because most installations run on the cluster CA's self-signed certificate, where an expiry two years out is not something to watch. It earns its place once you put a real certificate on the node — that is what tends to expire unnoticed.

The cluster CA itself (`pve-root-ca.pem`) is deliberately not reported: it is valid for ten years and its expiry is not something you act on.

This needs no permissions beyond being able to log in, and it is polled once an hour rather than once a minute, since certificates only change when someone replaces them.

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
> See the section on Proxmox user permissions [here](#proxmox-permissions).

### Tracking everything automatically

By default the integration tracks exactly the nodes, guests and storages you picked during setup, and a new VM shows up only once you add it in the integration options. The option **Track everything automatically** (in the same options step) turns that around: everything the credentials can see is tracked, and the cluster is followed from then on — a guest that is created is picked up within a minute, a guest that is deleted is dropped together with its device, and the same goes for nodes and storages. Templates are never tracked, because nothing on a template ever changes.

The selection lists are ignored while this is on, but they are not changed: what you picked stays stored exactly as it was, and switching the option off again brings that selection back at the next reload. Under the hood the integration brings its configuration in line with `GET /cluster/resources` at setup and keeps comparing once a minute. Like the Home Assistant core integration it then acts on the difference in place: a new node, guest or storage gets its coordinators, device and entities right away, a vanished one loses them — nothing is reloaded and nothing else goes unavailable.

Because `cluster/resources` only lists what the credentials may audit, "everything" means everything this user can see. A guest the user has no `VM.Audit` on is simply not there.

### When the configured host is down

Every request goes through the one host you configured; its `pveproxy` forwards to the other nodes. Until now that host being down took the whole cluster out of Home Assistant, however many nodes were still running.

The integration now asks `cluster/status` at setup what address every node answers on, and when the configured host stops answering it moves to the next node that does — logged as a warning — and keeps polling there. Nothing needs to be configured, and nothing is written to the entry: the configured host stays the one shown, and the next reload starts there again.

Two limits. The addresses in `cluster/status` are the ones the nodes joined the cluster on; if your cluster runs corosync on a separate network, Home Assistant cannot reach them and the fallback finds nothing — which leaves things exactly as they were before. And with **Verify SSL certificate** on, a fallback node has to present a certificate valid for that address, which per-node certificates usually are not.

### Nodes that are switched off for a while

With password authentication, a node that is off for longer than two hours used to demand new credentials when it came back: the login ticket had expired and its renewal was refused exactly like a wrong password. The integration now logs in again with the stored password before asking for anything, so a node that is off overnight simply resumes in the morning. A host that answers during boot but is not issuing tickets yet leaves setup retrying rather than asking for credentials. Tokens never had this problem; they do not expire.

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

## Install

### Installation via HACS

Have [HACS](https://hacs.xyz/) installed, this will allow you to update easily.

* Adding Proxmox VE to HACS can be using this button:

[![image](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=dougiteixeira&repository=proxmoxve&category=integration)

> [!NOTE]
> If the button above doesn't work, add `https://github.com/dougiteixeira/proxmoxve` as a custom repository of type Integration in HACS.

* Click Install on the `Proxmox VE` integration.
* Restart the Home Assistant.

<details><summary>Manual installation</summary>
 
* Copy `proxmoxve`  folder from [latest release](https://github.com/dougiteixeira/proxmoxve/releases/latest) to [`custom_components` folder](https://developers.home-assistant.io/docs/creating_integration_file_structure/#where-home-assistant-looks-for-integrations) in your config directory.
* Restart the Home Assistant.
</details>

## Configuration

Adding Proxmox VE to your Home Assistant instance can be done via the UI using this button:

[![image](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start?domain=proxmoxve)

> [!TIP]
> It is recommended to use token-based authentication for greater integration stability.
> 
> In your Home Assistant configuration, enter the token's **name** — the part after the `!` in what Proxmox shows as `Token ID`, e.g. `homeassistant` from `homeassistant@pve!homeassistant` — in the `Token name` field, and the secret token value in the password field. Pasting the full `user@realm!name` works too; the user and realm are taken from their own fields.

> [!NOTE]
> To use user-based authentication only, you must leave the `Token name` field empty in the configuration flow.

> [!IMPORTANT]
> It is important to correctly define the user's realm. The field offers `pam` (Linux users) and `pve` (users created in Proxmox) as a pick-list; for an LDAP, Active Directory or OpenID realm, type its name into the same field.
>
> You can check this in Proxmox under Datacenter > Permissions > Users > Realm column

<details><summary>Manual Configuration</summary>

If the button above doesn't work, you can also perform the following steps manually:

* Navigate to your Home Assistant instance.
* In the sidebar, click Settings.
* From the Setup menu, select: Devices & Services.
* In the lower right corner, click the Add integration button.
* In the list, search and select `Proxmox VE`.
* Follow the on-screen instructions to complete the setup.
</details>
 
## Debugging

To enable debug logging for a specific integration, follow these steps:

* Go to Settings > Devices & services.
* Select the integration card to open the detail page of the integration for which you want to enable debug logging.
* On the left side of the integration detail page, select Enable Debug Logging.

<details><summary>If you prefer, you can configure debugging through the `configuration.yaml` file</summary>

To enable debug for Proxmox VE integration, add following to your `configuration.yaml`:
```yaml
logger:
  default: info
  logs:
    custom_components.proxmoxve: debug
```
</details>

### Diagnostics

The integration supports Home Assistant's standard diagnostics download (Settings > Devices & services > Proxmox VE > ⋮ > Download diagnostics), useful for attaching to bug reports. It includes the config entry's settings (credentials redacted) and a snapshot of the last data polled by every active coordinator (nodes, VMs/CTs, storage, disks, ZFS, tasks, updates, and — if configured — the HA-managed resource list and cluster HA status). Node, VM/CT, and storage names are not redacted since they're the point of a diagnostics dump; review the file before sharing it publicly if that's a concern for your setup.

## Example screenshot:
Here are some screenshots of the integration

<details><summary>Node</summary>

![image](https://github.com/dougiteixeira/proxmoxve/assets/31328123/e371b34e-0449-499f-878b-b5baacee8a5e)

</details>

<details><summary>VM (QEMU)</summary>
 
![image](https://github.com/dougiteixeira/proxmoxve/assets/31328123/8213b877-8b23-4c4a-917b-04f27bb3a886)
 
</details>

<details><summary>Storage</summary>
 
![image](https://github.com/dougiteixeira/proxmoxve/assets/31328123/fb290802-95d7-4dcc-8538-d31636a2f6f8)
 
</details>

<details><summary>Physical disks</summary>
 
![image](https://github.com/dougiteixeira/proxmoxve/assets/31328123/f6174806-0ba8-4f60-ada7-cf5f29a1f629)
 
</details>

## Proxmox Permissions

> [!IMPORTANT]  
> It is necessary to reload the integration after changing user/token permissions in Proxmox.

To be able to obtain each type of integration information, the user used to connect must have the corresponding privilege.

It is not necessary to include all of the permission roles below, this will depend on your use of the integration.

The integration will create a repair for each resource that is exposed in the integration configuration but is not accessible by the user, indicating the path and privilege necessary to access it.

Control buttons are only created for actions the user may actually perform: at setup the integration reads the effective privileges of its credentials (`GET /access/permissions`) and leaves out, for instance, the `Reboot` button of a node without `Sys.PowerMgmt`, the `Create snapshot` button of a guest without `VM.Snapshot`, or the `Start` button of a guest without `VM.PowerMgmt`. A button that could only ever fail is not worth having. Grant the privilege and reload the integration to get the button back. Should the privileges not be readable at all, every button is created as before.

When executing a command, if the user does not have the necessary permission, a repair will be created indicating the path and privilege necessary to execute it.

> [!CAUTION]
> The permissions suggested in this documentation and in the created repairs are informative, the responsibility for assessing the risks involved in assigning permissions to the user is the sole responsibility of the user.

### Suggestion for creating permission roles for use with integration

Below is a summary of the permissions for each integration feature. I suggest you create the roles below to make it easier to assign only the necessary permissions to the user.

|Purpose of Permission|Access Type|Role (name suggestion)|Privilegies|
|---|---|---|---|
|Get data from nodes, VM, CT and storages|Read only|HomeAssistant.Audit|VM.Audit, Sys.Audit and Datastore.Audit|
|Perform commands on the node (shutdown, restart, start all, shutdown all)|Management permission|HomeAssistant.NodePowerMgmt|Sys.PowerMgmt|
|Get information about available package updates to display on sensors (integration does not trigger the update)|Management permission|HomeAssistant.Update|Sys.Modify|
|Perform commands on VM/CT (start, shutdown, restart, suspend, resume and hibernate)|Management permission|HomeAssistant.VMPowerMgmt|VM.PowerMgmt|
|**(Optional, separate user/token — see [Cluster HA Administration](#cluster-ha-administration-advanced-optional))** Arm/Disarm HA and read the HA-managed resource list and cluster HA status, root-scoped (`/`)|Cluster-wide management permission|HomeAssistant.ClusterHA|Sys.Console, Sys.Audit|

### Create Home Assistant Group

Before creating the user, we need to create a group for the user.
Privileges can be either applied to Groups or Roles.

1. Click `Datacenter`
2. Open `Permissions` and click `Groups`
3. Click the `Create` button above all the existing groups
4. Name the new group (e.g., `HomeAssistant`)
5. Click `Create`

### Add Group Permissions to all Assets

1. Click `Datacenter`
2. Click `Permissions`
3. Open `Add` and click `Group Permission`
4. Select the path of the resource you want to authorize the user to access. To enable all features select `/`
5. Select your Home Assistant group (`HomeAssistant`)
6. Select the role according to the table above (you must add a permission for each role in the table).
7. Make sure `Propagate` is checked

### Create Home Assistant User

Creating a dedicated user for Home Assistant, limited to only to the access just created is the most secure method. These instructions use the `pve` realm for the user. This allows a connection, but ensures that the user is not authenticated for SSH connections.

1. Click `Datacenter`
2. Open `Permissions` and click `Users`
3. Click `Add`
4. Enter a username (e.g.,` homeassistant`)
5. Set the realm to "Proxmox VE authentication server"
6. Enter a secure password (it can be complex as you will only need to copy/paste it into your Home Assistant configuration)
7. Select the group just created earlier (`HomeAssistant`) to grant access to Proxmox
8. Ensure `Enabled` is checked and `Expire` is set to "never"
9. Click `Add`

### Create token for user (recommended)

Creating a dedicated user token for Home Assistant, limited only to the newly created access, is the most recommended method.

1. Click `Datacenter`
2. Open `Permissions` and click `API Tokens`
3. Click `Add`
4. Select the user linked to the token
5. Enter a name for the token in the `Token ID` field (e.g.,` homeassistant`)
6. Decide how the token gets its permissions — this is the step most setups get wrong, see the note below:
   - **Uncheck `Privilege Separation`** and the token simply has the permissions of its user. Nothing else to do.
   - **Leave it checked** and the token has *no permissions of its own*, whatever its user may do. You then have to add the token itself (`homeassistant@pve!homeassistant`) to the same permission paths as the user, under `Datacenter → Permissions → Add → API Token Permission`.
7. Select the Never option in the `Expire` field
8. Ensure `Enabled` is checked and `Expire` is set to "never"
9. Click `Add`
10. Copy the secret token value

> [!WARNING]
> After closing the popup it is not possible to recover this value, if you lose the token value you must create a new token.

> [!IMPORTANT]
> **A token with `Privilege Separation` does not inherit anything from its user.** If the setup lists only the node and none of your VMs or containers, or the log says `Node <name> unable to be found`, while the user itself has every permission the table above asks for, this is why: the permissions sit on the user, the token has none. Either uncheck `Privilege Separation` on the token, or grant the token the same paths and roles as the user. Reload the integration afterwards.

> [!TIP]
> In your Home Assistant configuration, enter the token's **name** — `homeassistant` from a `Token ID` of `homeassistant@pve!homeassistant` — in the `Token name` field. The full id is accepted as well.

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

> [!NOTE]
> The `Create snapshot` button takes a disk-only snapshot (no RAM state) named `homeassistant_<date>_<time>` in your local time, described as "Created by Home Assistant" so it is recognisable in the snapshot list later. It needs `VM.Snapshot` on the guest; snapshots of a running container additionally need a storage that supports them.

> [!NOTE]
> The Wake on LAN button only works if the configured node is in a cluster of two or more nodes. If you want to use WOL on a single Node, use the official `Wake-On-Lan` integration.

## Translations
[![Crowdin](https://badges.crowdin.net/proxmoxve-homeassistant/localized.svg)](https://crowdin.com/project/proxmoxve-homeassistant)

You can help by adding missing translations when you are a native speaker. Or add a complete new language when there is no language file available.

Proxmox VE Custom Integration uses [Crowdin](https://crowdin.com) to make contributing easy.

### Changing or adding to existing language

First register and join the translation project:
* If you don’t have a Crowdin account yet, create one at https://crowdin.com
* Go to the [Proxmox VE Custom Integration for Home Assistant project page](https://crowdin.com/project/proxmoxve-homeassistant)
* Click Join.

Next translate a string:
* Select the language you want to contribute to from the dashboard.
* Click Translate All.
* Find the string you want to edit, missing translation are marked red.
* Fill in or modify the translation and click Save.
* Repeat for other translations.

### Adding a new language

[Create an Issue](https://github.com/dougiteixeira/proxmoxve/issues/new?template=new_language_request.yml&title=New+language) requesting a new language. We will do the necessary work to add the new translation to the integration and Crowdin site, when it's ready for you to contribute we'll comment on the issue you raised.
