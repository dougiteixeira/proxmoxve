[← README](https://github.com/dougiteixeira/proxmoxve#readme) · [Entities](entities.md) · [Actions](actions.md) · [Hardware sensors](hardware-sensors.md) · [Permissions](permissions.md) · [Behaviour](behaviour.md) · [Troubleshooting](troubleshooting.md) · [Compared with core](compared-to-core.md)

# Hardware sensors and physical disks

The integration automatically discovers and exposes hardware temperature, voltage, power, current, and fan speed sensors from Proxmox VE hosts via `lm-sensors`.

## Prerequisites

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

## When readings come and go

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

## Physical disks and SMART

The per-disk temperature, power-on hours, power cycles, wearout and health come from `nodes/{node}/disks/smart`. Proxmox hands that out in two shapes — smartctl's numbered attributes for SATA drives, and its text log for NVMe and SAS drives — and both are read, including the SAS labels (`Current Drive Temperature`, `Accumulated start-stop cycles`, `Accumulated power on time, hours:minutes`) an enterprise drive behind an expander uses. A value the drive does not have, such as a virtual NVMe reporting its temperature as `-`, is left out; it no longer takes the whole disk offline.

## Supported Hardware

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

## Auto-classification

Each sensor is automatically classified:

- **Names** mapped from known labels (e.g. `Tctl` → `CPU control temperature`, `edge` → `GPU hotspot`)
- **Units** inferred from sensor name patterns (temperature in °C, voltage in V, power in W, frequency in MHz, current in A, fan speed in RPM)
- **Device classes** set accordingly (`temperature`, `voltage`, `power`, `frequency`, `current`)
- **Icons** assigned per device type

Sensors are created under the corresponding Node device in Home Assistant and are marked as `diagnostic`.
