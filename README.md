# Proxmox VE Custom Integration for Home Assistant

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="custom_components/proxmoxve_custom/brand/dark_logo@2x.png">
  <img src="custom_components/proxmoxve_custom/brand/logo@2x.png">
</picture>

[Proxmox VE](https://www.proxmox.com/en/) is an open-source server virtualization environment. This integration reads its state into Home Assistant and lets you act on it — for a single node as much as for a cluster.

It began as [@dougiteixeira](https://github.com/dougiteixeira)'s custom integration, built on the [Home Assistant core integration](https://www.home-assistant.io/integrations/proxmoxve/) and grown well beyond it; it can run alongside the core one ([what differs](docs/compared-to-core.md)). Everything goes through the Proxmox API with the credentials you give it — nothing is installed on the nodes, except [PVE-mods](docs/hardware-sensors.md) if you want hardware temperatures.

## What you get

- **Cluster** — nodes online, guests running, CPU and memory across the cluster; HA status, backup coverage and Ceph health with the optional cluster credentials; shared storage as one device.
- **Nodes** — status, CPU, memory, swap, disk, IO delay, load average, version; package updates as a Home Assistant update entity; last backup and failed tasks; replication, subscription and certificate expiry; hardware temperatures, fans and voltages via PVE-mods; physical disks with SMART; ZFS pools.
- **Virtual machines and containers** — status with QEMU's finer run states, CPU (own and as a share of the host), memory, disk from the guest agent, network, uptime, a file read from inside the guest.
- **Storage** — capacity and the active/enabled/shared flags, per node for local storage and once for shared.
- **Actions** — start, stop, shutdown, reboot, suspend, resume, hibernate, reset, unlock, snapshot and backup buttons; bulk start/stop/suspend/backup per node; Wake on LAN; arm/disarm HA; and a `proxmoxve_custom.backup` action with all of vzdump's options.
- **Behaviour** — optional automatic discovery of everything the credentials can see, failover to another cluster node when the configured one goes down, no re-authentication after a node was off overnight, repairs that name the missing privilege, and buttons only where the privilege exists.

Many entities are created **disabled by default** — the buttons that change things, and sensors most setups never need — and are enabled per entity, see [Disabled entities](docs/behaviour.md#disabled-entities).

## Documentation

- [Entities](docs/entities.md) — every sensor, by cluster, node, guest and storage
- [Actions](docs/actions.md) — buttons and the `proxmoxve_custom.backup` action
- [Hardware sensors and physical disks](docs/hardware-sensors.md) — PVE-mods, SMART, when readings come and go
- [Proxmox permissions](docs/permissions.md) — roles, group, user and token, step by step
- [How it behaves](docs/behaviour.md) — discovery, failover, nodes that are off, disabled entities, what I cannot test
- [Troubleshooting](docs/troubleshooting.md) — debug logging, diagnostics, screenshots
- [Compared with the core integration](docs/compared-to-core.md) — what the extra install gets you, feature by feature
- [Blueprints](blueprints/readme.md) — a scheduled backup as a ready-made automation
- [Contributing](CONTRIBUTING.md)

## Updating the domain from `proxmoxve` to `proxmoxve_custom`

>[!TIP]
> The migration steps below apply only if you already have the integration configured with a version earlier than 6.0.0 and wish to retain your existing configuration, including entity names, IDs, and customizations.
> Alternatively, you may uninstall and reinstall the integration and set up a new configuration entry. Please note that doing so will remove all current devices, entities, and customizations.

The integration was originally created using the `proxmoxve` domain—the same one used by the official integration—which means both cannot be used simultaneously.

Version [6.0.0b0](https://github.com/dougiteixeira/proxmoxve/releases/tag/6.0.0b0) introduces an automatic domain migration, ensuring that your existing configuration entries, devices, and entities are preserved.

Please follow the instructions provided in the [6.0.0b0 release notes](https://github.com/dougiteixeira/proxmoxve/releases/tag/6.0.0b0) to perform the update. This update must be carried out manually due to Marketplace restrictions.

## Install

### Installation via the Marketplace (Home Assistant 2026.11 and newer)

HACS is built into Home Assistant as the Marketplace. Proxmox VE is not in its catalog, so it is added as a custom repository - this button does that:

[![Open your Home Assistant instance and open a repository in the Marketplace.](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=dougiteixeira&repository=proxmoxve&category=integration)

The Marketplace asks before it adds the repository, and it needs a connected GitHub account for it. Without the button: Settings > Marketplace > Custom repositories, add `https://github.com/dougiteixeira/proxmoxve` as type Integration.

* Click Install on `Proxmox VE Custom`.
* Restart Home Assistant if the Marketplace asks for it.

An installation from HACS moves to the Marketplace by itself when Home Assistant is updated to 2026.11.

### Installation via HACS (before Home Assistant 2026.11)

Have [HACS](https://hacs.xyz/) installed, this will allow you to update easily.

* Add Proxmox VE to HACS with the same button as above. If it does not work, add `https://github.com/dougiteixeira/proxmoxve` as a custom repository of type Integration in HACS.
* Click Install on the `Proxmox VE Custom` integration.
* Restart Home Assistant.

**Manual installation**

* Copy the `proxmoxve_custom` folder from the repository to the [`custom_components` folder](https://developers.home-assistant.io/docs/creating_integration_file_structure/#where-home-assistant-looks-for-integrations) in your config directory. For an existing installation, see [Updating the domain](#updating-the-domain-from-proxmoxve-to-proxmoxve_custom).
* Restart the Home Assistant.

## Configuration

Adding Proxmox VE to your Home Assistant instance can be done via the UI using this button:

[![image](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start?domain=proxmoxve_custom)

**Tip:** It is recommended to use token-based authentication for greater integration stability.

In your Home Assistant configuration, enter the token's **name** — the part after the `!` in what Proxmox shows as `Token ID`, e.g. `homeassistant` from `homeassistant@pve!homeassistant` — in the `Token name` field, and the secret token value in the password field. Pasting the full `user@realm!name` works too; the user and realm are taken from their own fields.

**Note:** To use user-based authentication only, you must leave the `Token name` field empty in the configuration flow.

**Important:** It is important to correctly define the user's realm. The field offers `pam` (Linux users) and `pve` (users created in Proxmox) as a pick-list; for an LDAP, Active Directory or OpenID realm, type its name into the same field.

You can check this in Proxmox under Datacenter > Permissions > Users > Realm column

If the button doesn't work, add it by hand: Settings → Devices & Services → Add integration → search for `Proxmox VE` and follow the on-screen instructions.

### Options

Everything beyond the credentials lives in the integration options (Settings → Devices & services → Proxmox VE → Configure), split into the selection and an **Advanced configuration** page:

- **Add or remove nodes, VMs, containers or storages** — what is tracked. Shared storage is listed once, marked *(shared)*.
- **Monitor physical disks** — the per-disk devices with SMART, temperature and wearout. Reading SMART wakes sleeping disks, which is why it can be switched off.
- **Polling interval** — 30, 45, 60, 90 or 120 seconds for nodes, guests, storage and backups; certificates, subscriptions and Ceph stay hourly, failed tasks at five minutes.
- **Monitor package updates** — the [update entity](docs/entities.md#package-updates); off means no `Sys.Modify` needed.
- **Monitor failed tasks** — the [failed task sensors](docs/entities.md#failed-task-monitoring).
- **Track everything automatically** — [discovery](docs/behaviour.md#tracking-everything-automatically): follow the cluster instead of a fixed selection.
- **Guest file path to monitor** — the [guest file content sensor](docs/entities.md#guest-file-content-sensor).
- **Backup storage for the backup buttons** — the [backup buttons](docs/actions.md#backup-buttons) exist only while this is set.
- **Entity id scheme** — standard (Home Assistant's device then name) or extended (`pve_<kind>_<id>_<name>_<item>`, with the prefix of your choice); chosen at setup, existing ids never change ([details](docs/behaviour.md#entity-ids)).
- **Optional: cluster HA administration** — a second set of credentials for the [cluster-wide features](docs/entities.md#cluster-ha-administration-advanced-optional).

## Permissions

The credentials need `VM.Audit`, `Sys.Audit` and `Datastore.Audit` on what you track to read — plus `VM.GuestAgent.Audit` for a VM's disk usage from inside the guest — and more to act — `VM.PowerMgmt` for a guest's power buttons, `Sys.PowerMgmt` for a node's, `VM.Snapshot`, `VM.Backup`, `Sys.Modify` for package updates. Buttons exist only where the privilege is held, and a repair names what is missing. The step-by-step guide for roles, group, user and token — including the one token setting most setups get wrong — is in [Proxmox permissions](docs/permissions.md).

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

[← README](#) · [Entities](entities.md) · [Actions](actions.md) · [Hardware sensors](hardware-sensors.md) · [Permissions](permissions.md) · [Behaviour](behaviour.md) · [Troubleshooting](troubleshooting.md) · [Compared with core](compared-to-core.md)/
