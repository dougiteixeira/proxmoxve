# Proxmox VE Custom Integration for Home Assistant

![Proxmox VE Custom Integration](https://github.com/dougiteixeira/proxmoxve/assets/31328123/dfec7426-852d-41ea-b6c1-9bfd8cd1e8a8)

[Proxmox VE](https://www.proxmox.com/en/) is an open-source server virtualization environment. This integration reads its state into Home Assistant and lets you act on it — for a single node as much as for a cluster.

It began as [@dougiteixeira](https://github.com/dougiteixeira)'s custom integration, built on the [Home Assistant core integration](https://www.home-assistant.io/integrations/proxmoxve/) and grown well beyond it; it replaces the core one when installed. Everything goes through the Proxmox API with the credentials you give it — nothing is installed on the nodes, except [PVE-mods](https://github.com/dougiteixeira/proxmoxve/blob/main/docs/hardware-sensors.md) if you want hardware temperatures.

## What you get

- **Cluster** — nodes online, guests running, CPU and memory across the cluster; HA status, backup coverage and Ceph health with the optional cluster credentials; shared storage as one device.
- **Nodes** — status, CPU, memory, swap, disk, IO delay, load average, version; package updates as a Home Assistant update entity; last backup and failed tasks; replication, subscription and certificate expiry; hardware temperatures, fans and voltages via PVE-mods; physical disks with SMART; ZFS pools.
- **Virtual machines and containers** — status with QEMU's finer run states, CPU (own and as a share of the host), memory, disk from the guest agent, network, uptime, a file read from inside the guest.
- **Storage** — capacity and the active/enabled/shared flags, per node for local storage and once for shared.
- **Actions** — start, stop, shutdown, reboot, suspend, resume, hibernate, reset, unlock, snapshot and backup buttons; bulk start/stop/suspend/backup per node; Wake on LAN; arm/disarm HA; and a `proxmoxve.backup` action with all of vzdump's options.
- **Behaviour** — optional automatic discovery of everything the credentials can see, failover to another cluster node when the configured one goes down, no re-authentication after a node was off overnight, repairs that name the missing privilege, and buttons only where the privilege exists.

Many entities are created **disabled by default** — the buttons that change things, and sensors most setups never need — and are enabled per entity, see [Disabled entities](https://github.com/dougiteixeira/proxmoxve/blob/main/docs/behaviour.md#disabled-entities).

## Documentation

- [Entities](https://github.com/dougiteixeira/proxmoxve/blob/main/docs/entities.md) — every sensor, by cluster, node, guest and storage
- [Actions](https://github.com/dougiteixeira/proxmoxve/blob/main/docs/actions.md) — buttons and the `proxmoxve.backup` action
- [Hardware sensors and physical disks](https://github.com/dougiteixeira/proxmoxve/blob/main/docs/hardware-sensors.md) — PVE-mods, SMART, when readings come and go
- [Proxmox permissions](https://github.com/dougiteixeira/proxmoxve/blob/main/docs/permissions.md) — roles, group, user and token, step by step
- [How it behaves](https://github.com/dougiteixeira/proxmoxve/blob/main/docs/behaviour.md) — discovery, failover, nodes that are off, disabled entities, what I cannot test
- [Troubleshooting](https://github.com/dougiteixeira/proxmoxve/blob/main/docs/troubleshooting.md) — debug logging, diagnostics, screenshots
- [Contributing](https://github.com/dougiteixeira/proxmoxve/blob/main/CONTRIBUTING.md)

## Install

### Installation via HACS

Have [HACS](https://hacs.xyz/) installed, this will allow you to update easily.

* Adding Proxmox VE to HACS can be using this button:

[![image](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=dougiteixeira&repository=proxmoxve&category=integration)

If the button above doesn't work, add `https://github.com/dougiteixeira/proxmoxve` as a custom repository of type Integration in HACS.

* Click Install on the `Proxmox VE` integration.
* Restart the Home Assistant.

**Manual installation**

* Copy the `proxmoxve` folder from [latest release](https://github.com/dougiteixeira/proxmoxve/releases/latest) to [`custom_components` folder](https://developers.home-assistant.io/docs/creating_integration_file_structure/#where-home-assistant-looks-for-integrations) in your config directory.
* Restart the Home Assistant.

## Configuration

Adding Proxmox VE to your Home Assistant instance can be done via the UI using this button:

[![image](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start?domain=proxmoxve)

**Tip:** It is recommended to use token-based authentication for greater integration stability.

In your Home Assistant configuration, enter the token's **name** — the part after the `!` in what Proxmox shows as `Token ID`, e.g. `homeassistant` from `homeassistant@pve!homeassistant` — in the `Token name` field, and the secret token value in the password field. Pasting the full `user@realm!name` works too; the user and realm are taken from their own fields.

**Note:** To use user-based authentication only, you must leave the `Token name` field empty in the configuration flow.

**Important:** It is important to correctly define the user's realm. The field offers `pam` (Linux users) and `pve` (users created in Proxmox) as a pick-list; for an LDAP, Active Directory or OpenID realm, type its name into the same field.

You can check this in Proxmox under Datacenter > Permissions > Users > Realm column

If the button doesn't work, add it by hand: Settings → Devices & Services → Add integration → search for `Proxmox VE` and follow the on-screen instructions.

### Options

Everything beyond the credentials lives in the integration options (Settings → Devices & services → Proxmox VE → Configure):

- **Add or remove nodes, VMs, containers or storages** — what is tracked. Shared storage is listed once, marked *(shared)*.
- **Enable physical disk information** — the per-disk devices with SMART, temperature and wearout. Reading SMART wakes sleeping disks, which is why it can be switched off.
- **Monitor failed tasks** — the [failed task sensors](https://github.com/dougiteixeira/proxmoxve/blob/main/docs/entities.md#failed-task-monitoring).
- **Track everything automatically** — [discovery](https://github.com/dougiteixeira/proxmoxve/blob/main/docs/behaviour.md#tracking-everything-automatically): follow the cluster instead of a fixed selection.
- **Guest file path to monitor** — the [guest file content sensor](https://github.com/dougiteixeira/proxmoxve/blob/main/docs/entities.md#guest-file-content-sensor).
- **Backup storage for the backup buttons** — the [backup buttons](https://github.com/dougiteixeira/proxmoxve/blob/main/docs/actions.md#backup-buttons) exist only while this is set.
- **Optional: cluster HA administration** — a second set of credentials for the [cluster-wide features](https://github.com/dougiteixeira/proxmoxve/blob/main/docs/entities.md#cluster-ha-administration-advanced-optional).

## Permissions

The credentials need `VM.Audit`, `Sys.Audit` and `Datastore.Audit` on what you track to read, and more to act — `VM.PowerMgmt` for a guest's power buttons, `Sys.PowerMgmt` for a node's, `VM.Snapshot`, `VM.Backup`, `Sys.Modify` for package updates. Buttons exist only where the privilege is held, and a repair names what is missing. The step-by-step guide for roles, group, user and token — including the one token setting most setups get wrong — is in [Proxmox permissions](https://github.com/dougiteixeira/proxmoxve/blob/main/docs/permissions.md).

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
