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

### Ceph health

Clusters running Ceph get a `Ceph health` sensor on the `Proxmox Cluster` device — `ok`, `warning` or `error` — with the failing checks (name, severity, message) as an attribute. **Disabled by default.**

Only the health block is read. The response also carries the monitor, OSD and placement group maps, which are a different question and a great deal of data to put behind a sensor.

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
> In your Home Assistant configuration, enter the value defined in `Token ID` in the `Token name` field and enter the secret token value in the password field.

> [!NOTE]
> To use user-based authentication only, you must leave the `Token name` field empty in the configuration flow.

> [!IMPORTANT]
> It is important to correctly define the user's realm (`pam`, `pve` or other).
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
6. Uncheck the `Privilege Separation` option to unlink user permissions (in this case, unique permissions must be configured for the token)
7. Select the Never option in the `Expire` field
8. Ensure `Enabled` is checked and `Expire` is set to "never"
9. Click `Add`
10. Copy the secret token value

> [!WARNING]
> After closing the popup it is not possible to recover this value, if you lose the token value you must create a new token.

> [!TIP]
> In your Home Assistant configuration, enter the value defined in `Token ID` in the `Token name` field.

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
