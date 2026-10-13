[← README](https://github.com/dougiteixeira/proxmoxve#readme) · [Entities](entities.md) · [Actions](actions.md) · [Hardware sensors](hardware-sensors.md) · [Permissions](permissions.md) · [Behaviour](behaviour.md) · [Troubleshooting](troubleshooting.md) · [Compared with core](compared-to-core.md)

# Troubleshooting

## Debug logging

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

## "Everything is 0" or a node that cannot be read

Proxmox filters what it lists by privilege rather than refusing the request, so credentials that may not see a node, a guest or a storage get an empty list — not an error. The integration then has nothing to show, and the node reads as unreadable.

The usual cause is an API token: Proxmox creates them with **Privilege Separation** on, and such a token holds only what is granted to the token itself, not what its user has. Compare the two on any node:

```bash
pvesh get /access/permissions --userid 'user@realm!tokenname'
pvesh get /access/permissions --userid 'user@realm'
```

If the token's list is empty and the user's is not, either untick *Privilege Separation* on the token or give the token its own ACL, as in [Permissions](permissions.md). A refused read also creates a repair naming the privilege and the path it wanted.

## Diagnostics

The integration supports Home Assistant's standard diagnostics download (Settings > Devices & services > Proxmox VE > ⋮ > Download diagnostics), useful for attaching to bug reports. It includes the config entry's settings (credentials redacted) and a snapshot of the last data polled by every active coordinator (nodes, VMs/CTs, storage, disks, ZFS, tasks, updates, and — if configured — the HA-managed resource list and cluster HA status). Node, VM/CT, and storage names are not redacted since they're the point of a diagnostics dump; review the file before sharing it publicly if that's a concern for your setup.

## Screenshots

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
