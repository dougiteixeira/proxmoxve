# Proxmox VE Custom Integration for Home Assistant

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://github.com/user-attachments/assets/5b5a8c5b-885b-4233-a858-2e78b97d8c74">
  <img src="https://github.com/dougiteixeira/proxmoxve/assets/31328123/dfec7426-852d-41ea-b6c1-9bfd8cd1e8a8">
</picture>

[Proxmox VE](https://www.proxmox.com/en/) is an open-source server virtualization environment. This integration reads its state into Home Assistant and lets you act on it — for a single node as much as for a cluster.

It began as [@dougiteixeira](https://github.com/dougiteixeira)'s custom integration, built on the [Home Assistant core integration](https://www.home-assistant.io/integrations/proxmoxve/) and grown well beyond it; it replaces the core one when installed ([what differs](https://github.com/dougiteixeira/proxmoxve/blob/main/docs/compared-to-core.md)). Everything goes through the Proxmox API with the credentials you give it — nothing is installed on the nodes, except [PVE-mods](https://github.com/dougiteixeira/proxmoxve/blob/main/docs/hardware-sensors.md) if you want hardware temperatures.

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
- [Compared with the core integration](https://github.com/dougiteixeira/proxmoxve/blob/main/docs/compared-to-core.md) — what the extra install gets you, feature by feature
- [Blueprints](https://github.com/dougiteixeira/proxmoxve/blob/main/blueprints/readme.md) — a scheduled backup as a ready-made automation
- [Contributing](https://github.com/dougiteixeira/proxmoxve/blob/main/CONTRIBUTING.md)

## Install

### Migrating to `proxmoxve_custom`

Back up Home Assistant before migrating from the `proxmoxve` domain. Only
legacy configuration entries at version **7** are eligible. The replacement
entry uses version **1** under the new domain. Entries at any other version
are not transferred; historical upgrades can remove devices, so plan those
upgrades separately and keep a backup.

Legacy entries at versions 1 to 6 remain on `proxmoxve` and raise a repair
requesting version 5.3.5. Back up Home Assistant, install that version and
restart; verify the entry and devices before attempting the domain migration.
Home Assistant rejects entry versions higher than 7 before the integration can
load them; do not downgrade such entries without a compatible backup.

> [!WARNING]
> Do not install the legacy transition component if this Home Assistant instance
> has entries from the built-in Proxmox VE integration. Both use the `proxmoxve`
> domain, so the transition component overrides the built-in integration and
> can prevent its entries from loading. The transition does not migrate native
> entries and cannot keep them working while the legacy component is installed.

The commands below require release `6.0.0b0` and the ZIP assets named below.
The final Marketplace step requires version `6.0.0` to be published. The
commands require shell access to the Home Assistant configuration directory,
`curl` and `unzip`. Replace `/config` if your configuration directory is
elsewhere.

#### 1. Install version 6.0.0b0

This transition release installs both components and migrates eligible legacy
entries. Do not remove the integration from Devices & Services.

```bash
cd /config &&
  mkdir -p custom_components/proxmoxve custom_components/proxmoxve_custom &&
  curl -fL -o /tmp/proxmoxve-6.0.0b0.zip \
    https://github.com/dougiteixeira/proxmoxve/releases/download/6.0.0b0/proxmoxve.zip &&
  curl -fL -o /tmp/proxmoxve-custom-6.0.0b0.zip \
    https://github.com/dougiteixeira/proxmoxve/releases/download/6.0.0b0/proxmoxve_custom.zip &&
  unzip -o /tmp/proxmoxve-6.0.0b0.zip -d custom_components/proxmoxve &&
  unzip -o /tmp/proxmoxve-custom-6.0.0b0.zip -d custom_components/proxmoxve_custom
```

Restart Home Assistant. Each enabled, eligible legacy entry is migrated
automatically; disabled entries must be enabled to start migration. Use the
restart button in the repair that appears, then verify the new entry, devices,
entities and automations. Restore the backup if the migration does not succeed.

#### 2. Check the legacy component

The new integration removes the recognized legacy directory automatically
once no legacy entries or incomplete migrations remain. If the directory is
already absent, continue to the next step.

If the directory remains, first verify that **all** legacy entries, including
disabled entries, have migrated and that the directory belongs to this legacy
integration. Do not remove it while any legacy entry or migration is pending.
Once verified, you can remove a regular directory manually:

```bash
cd /config &&
  if [[ -L custom_components/proxmoxve ]]; then
    printf 'Legacy path is a symbolic link; inspect it before removing it.\n'
  elif [[ -d custom_components/proxmoxve ]]; then
    rm -r -- custom_components/proxmoxve
  else
    printf 'Legacy directory is already absent.\n'
  fi
```

Restart Home Assistant if you removed the directory manually.

#### 3. Install version 6.0.0 through the Marketplace

After verifying the migration, uninstall the old repository **from the
Marketplace**, not from Devices & Services. Install the repository again through
the Marketplace and select version `6.0.0`. This resets the Marketplace's
recorded domain without deleting the migrated configuration entry. Restart if
the Marketplace requests it. Subsequent updates can then be installed through
the Marketplace.

The new entry receives a new entry ID. Its settings, options, devices, device
IDs and entity IDs are transferred, and entity unique IDs are adjusted to
match the new entry. The `proxmoxve.backup` action remains available as an
alias for `proxmoxve_custom.backup`. A detected registry conflict stops the
transfer; check the Home Assistant logs before retrying.

After the new integration starts successfully and all legacy entries have
been removed, it removes the recognized legacy `custom_components/proxmoxve`
directory. It leaves the directory in place while disabled, incompatible or
incomplete legacy entries remain, or if it is a symbolic link or does not
match this integration's manifest. Cleanup is retried on subsequent starts;
check the logs if file permissions prevent removal.

The Marketplace does not update an installed repository when its domain changes;
the manual transition and Marketplace reinstallation above are required for
existing installations. The new release must advertise `proxmoxve_custom` in
its root manifest and in the `proxmoxve_custom.zip` manifest. Once reinstalled,
subsequent Marketplace updates install only `proxmoxve_custom`.

### Installation via the Marketplace (Home Assistant 2026.11 and newer)

HACS is built into Home Assistant as the Marketplace. Proxmox VE is not in its catalog, so it is added as a custom repository - this button does that:

[![image](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=dougiteixeira&repository=proxmoxve&category=integration)

The Marketplace asks before it adds the repository, and it needs a connected GitHub account for it. Without the button: Settings > Marketplace > Custom repositories, add `https://github.com/dougiteixeira/proxmoxve` as type Integration.

* Click Install on `Proxmox VE`.
* Restart Home Assistant if the Marketplace asks for it.

An installation from HACS moves to the Marketplace by itself when Home Assistant is updated to 2026.11.

### Installation via HACS (before Home Assistant 2026.11)

Have [HACS](https://hacs.xyz/) installed, this will allow you to update easily.

* Add Proxmox VE to HACS with the same button as above. If it does not work, add `https://github.com/dougiteixeira/proxmoxve` as a custom repository of type Integration in HACS.
* Click Install on the `Proxmox VE` integration.
* Restart Home Assistant.

**Manual installation**

* Copy the `proxmoxve_custom` folder from the repository to the [`custom_components` folder](https://developers.home-assistant.io/docs/creating_integration_file_structure/#where-home-assistant-looks-for-integrations) in your config directory. For an existing installation, also install the transition release's `proxmoxve` component as described under Migrating to `proxmoxve_custom`.
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
- **Monitor package updates** — the [update entity](https://github.com/dougiteixeira/proxmoxve/blob/main/docs/entities.md#package-updates); off means no `Sys.Modify` needed.
- **Monitor failed tasks** — the [failed task sensors](https://github.com/dougiteixeira/proxmoxve/blob/main/docs/entities.md#failed-task-monitoring).
- **Track everything automatically** — [discovery](https://github.com/dougiteixeira/proxmoxve/blob/main/docs/behaviour.md#tracking-everything-automatically): follow the cluster instead of a fixed selection.
- **Guest file path to monitor** — the [guest file content sensor](https://github.com/dougiteixeira/proxmoxve/blob/main/docs/entities.md#guest-file-content-sensor).
- **Backup storage for the backup buttons** — the [backup buttons](https://github.com/dougiteixeira/proxmoxve/blob/main/docs/actions.md#backup-buttons) exist only while this is set.
- **Entity id scheme** — standard (Home Assistant's device then name) or extended (`pve_<kind>_<id>_<name>_<item>`, with the prefix of your choice); chosen at setup, existing ids never change ([details](https://github.com/dougiteixeira/proxmoxve/blob/main/docs/behaviour.md#entity-ids)).
- **Optional: cluster HA administration** — a second set of credentials for the [cluster-wide features](https://github.com/dougiteixeira/proxmoxve/blob/main/docs/entities.md#cluster-ha-administration-advanced-optional).

## Permissions

The credentials need `VM.Audit`, `Sys.Audit` and `Datastore.Audit` on what you track to read — plus `VM.GuestAgent.Audit` for a VM's disk usage from inside the guest — and more to act — `VM.PowerMgmt` for a guest's power buttons, `Sys.PowerMgmt` for a node's, `VM.Snapshot`, `VM.Backup`, `Sys.Modify` for package updates. Buttons exist only where the privilege is held, and a repair names what is missing. The step-by-step guide for roles, group, user and token — including the one token setting most setups get wrong — is in [Proxmox permissions](https://github.com/dougiteixeira/proxmoxve/blob/main/docs/permissions.md).

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
