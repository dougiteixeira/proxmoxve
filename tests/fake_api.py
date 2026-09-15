# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""
A Proxmox API that answers each path with its own, realistic response.

The older tests patch `ProxmoxResource.get` to return one guest list for
every path. That passes setup only because the migration a version-1 entry
goes through loses the node name, so the node paths are never really
exercised; give the mock a real node and the disk lookup falls over the
guest list. This fake keeps a route table keyed by the path after
`/api2/json/`, exactly as the integration spells it, query string included.

`default_routes()` describes one node, `pve`, with a VM, a container, two
storages, one disk, one ZFS pool, pending updates and a finished backup.
Every value is invented; the shapes follow the Proxmox VE 9 API.
"""

from __future__ import annotations

import copy
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

from proxmoxer.core import ResourceException

if TYPE_CHECKING:
    from collections.abc import Iterator

API_ROOT = "/api2/json/"

NODE = "pve"
NOW = 1767225600  # 2026-01-01 00:00:00 UTC, as the task log would report it

STORAGE_LOCAL = {
    "id": f"storage/{NODE}/local",
    "storage": "local",
    "node": NODE,
    "type": "storage",
    "plugintype": "dir",
    "status": "available",
    "content": "backup,iso,vztmpl",
    "disk": 14_395_699_200,
    "maxdisk": 100_861_726_720,
    "shared": 0,
}
STORAGE_EXT = {
    "id": f"storage/{NODE}/ext",
    "storage": "ext",
    "node": NODE,
    "type": "storage",
    "plugintype": "nfs",
    "status": "available",
    "content": "backup,images",
    "disk": 414_336_409_600,
    "maxdisk": 471_416_549_376,
    "shared": 1,
}


def guest_resource(kind: str, vmid: int, name: str, status: str = "running") -> dict:
    """Return a guest as `cluster/resources` lists it."""
    return {
        "id": f"{kind}/{vmid}",
        "type": kind,
        "vmid": vmid,
        "name": name,
        "node": NODE,
        "status": status,
        "template": 0,
        "cpu": 0.02,
        "maxcpu": 2,
        "mem": 268_435_456,
        "maxmem": 1_073_741_824,
        "disk": 0 if kind == "qemu" else 911_167_488,
        "maxdisk": 34_359_738_368 if kind == "qemu" else 2_040_373_248,
        "netin": 370_783_656,
        "netout": 117_493_824,
        "diskread": 983_932_928,
        "diskwrite": 100_974_592,
        "uptime": 309_943 if status == "running" else 0,
    }


def qemu_status(vmid: int, name: str, status: str = "running") -> dict:
    """Return a VM as `nodes/{node}/qemu/{vmid}/status/current` reports it."""
    running = status == "running"
    return {
        "vmid": vmid,
        "name": name,
        "status": status,
        "qmpstatus": status,
        "agent": 1,
        "cpu": 0.048 if running else 0,
        "cpus": 4,
        "mem": 3_519_520_768 if running else 0,
        "maxmem": 8_589_934_592,
        "balloon": 8_589_934_592,
        "ballooninfo": {
            "total_mem": 8_150_000_000,
            "free_mem": 4_600_000_000,
            "actual": 8_589_934_592,
        },
        "disk": 0,
        "maxdisk": 34_359_738_368,
        "netin": 90_068_966_355,
        "netout": 31_171_753_430,
        "diskread": 3_157_159_936,
        "diskwrite": 18_522_621_440,
        "uptime": 309_941 if running else 0,
        "pid": 1234 if running else None,
        "ha": {"managed": 0},
    }


def lxc_status(vmid: int, name: str, status: str = "running") -> dict:
    """Return a container as `nodes/{node}/lxc/{vmid}/status/current` reports it."""
    running = status == "running"
    return {
        "vmid": vmid,
        "name": name,
        "status": status,
        "type": "lxc",
        "cpu": 0.0003 if running else 0,
        "cpus": 2,
        "mem": 18_821_120 if running else 0,
        "maxmem": 1_073_741_824,
        "swap": 0,
        "maxswap": 536_870_912,
        "disk": 911_167_488,
        "maxdisk": 2_040_373_248,
        "netin": 370_783_656,
        "netout": 117_493_824,
        "diskread": 983_932_928,
        "diskwrite": 100_974_592,
        "uptime": 309_943 if running else 0,
        "ha": {"managed": 0},
    }


def default_routes() -> dict[str, Any]:
    """Return a fresh route table for one node with a VM and a container."""
    vm = guest_resource("qemu", 101, "vm-test-101")
    ct = guest_resource("lxc", 100, "lxc-test-100")
    node = {
        "id": f"node/{NODE}",
        "node": NODE,
        "type": "node",
        "status": "online",
        "level": "",
        "cpu": 0.0135,
        "maxcpu": 8,
        "mem": 12_884_901_888,
        "maxmem": 33_567_272_960,
        "disk": 8_589_934_592,
        "maxdisk": 100_861_726_720,
        "uptime": 1_209_600,
    }
    return {
        "cluster/resources": [
            node,
            vm,
            ct,
            STORAGE_LOCAL,
            STORAGE_EXT,
            {"id": f"sdn/{NODE}/localnetwork", "type": "sdn", "node": NODE},
        ],
        "cluster/resources?type=storage": [STORAGE_LOCAL, STORAGE_EXT],
        "access/permissions": {
            "/": {
                "Sys.Audit": 1,
                "Sys.Modify": 1,
                "Sys.PowerMgmt": 1,
                "VM.Audit": 1,
                "VM.PowerMgmt": 1,
                "VM.Snapshot": 1,
                "VM.Config.Options": 1,
                "Datastore.Audit": 1,
            }
        },
        "nodes": [node],
        f"nodes/{NODE}/status": {
            "cpuinfo": {"model": "AMD Ryzen 5 2400G", "cpus": 8, "sockets": 1},
            "memory": {
                "total": 33_567_272_960,
                "used": 12_884_901_888,
                "free": 20_682_371_072,
            },
            "swap": {"total": 8_589_934_592, "used": 0, "free": 8_589_934_592},
            "rootfs": {
                "total": 100_861_726_720,
                "used": 8_589_934_592,
                "avail": 87_000_000_000,
                "free": 92_271_792_128,
            },
            "uptime": 1_209_600,
            "loadavg": ["0.10", "0.12", "0.09"],
            "kversion": "Linux 6.14.11-2-pve",
            "pveversion": "pve-manager/9.0.6/1234abcd",
        },
        f"nodes/{NODE}/version": {
            "version": "9.0.6",
            "release": "9.0",
            "repoid": "1234abcd",
        },
        f"nodes/{NODE}/qemu": [vm],
        f"nodes/{NODE}/lxc": [ct],
        f"nodes/{NODE}/apt/update": [
            {
                "Package": "pve-manager",
                "Title": "Proxmox Virtual Environment Management Tools",
                "Version": "9.0.10",
                "OldVersion": "9.0.6",
                "Origin": "Proxmox",
            },
            {
                "Package": "openssl",
                "Title": "Secure Sockets Layer toolkit - cryptographic utility",
                "Version": "3.5.1-1+deb13u1",
                "OldVersion": "3.5.1-1",
                "Origin": "Debian",
            },
        ],
        f"nodes/{NODE}/certificates/info": [
            {
                "filename": "pve-root-ca.pem",
                "subject": "/CN=Proxmox Virtual Environment/OU=abc/O=PVE Cluster Manager CA",
                "issuer": "/CN=Proxmox Virtual Environment/OU=abc/O=PVE Cluster Manager CA",
                "notbefore": NOW - 86_400 * 30,
                "notafter": NOW + 86_400 * 3650,
            },
            {
                "filename": "pve-ssl.pem",
                "subject": f"/OU=PVE Cluster Node/O=Proxmox Virtual Environment/CN={NODE}.local",
                "issuer": "/CN=Proxmox Virtual Environment/OU=abc/O=PVE Cluster Manager CA",
                "notbefore": NOW - 86_400 * 30,
                "notafter": NOW + 86_400 * 700,
            },
        ],
        f"nodes/{NODE}/subscription": {
            "status": "notfound",
            "message": "There is no subscription key",
            "serverid": "0000000000000000000000000000000A",
            "url": "https://www.example.invalid/pricing",
        },
        f"nodes/{NODE}/replication": [],
        f"nodes/{NODE}/tasks?typefilter=vzdump&source=archive&limit=1": [
            {
                "upid": f"UPID:{NODE}:00001234:0000ABCD:69554B80:vzdump:100,101:root@pam:",
                "node": NODE,
                "type": "vzdump",
                "id": "100,101",
                "user": "root@pam",
                "starttime": NOW - 3600,
                "endtime": NOW - 2400,
                "status": "OK",
            }
        ],
        f"nodes/{NODE}/tasks": [
            {
                "upid": f"UPID:{NODE}:00001235:0000ABCE:69554C00:qmstart:101:root@pam:",
                "node": NODE,
                "type": "qmstart",
                "id": "101",
                "user": "root@pam",
                "starttime": NOW - 1800,
                "endtime": NOW - 1790,
                "status": "OK",
            }
        ],
        f"nodes/{NODE}/disks/list": [
            {
                "devpath": "/dev/sda",
                "by_id_link": "/dev/disk/by-id/ata-SAMSUNG_SSD_S123",
                "serial": "S123",
                "wwn": "0x5002538e40000001",
                "model": "SAMSUNG_SSD_870",
                "vendor": "ATA",
                "type": "ssd",
                "size": 500_107_862_016,
                "health": "PASSED",
                "wearout": 98,
                "rpm": 0,
                "gpt": 1,
                "used": "ZFS",
                "osdid": -1,
            }
        ],
        f"nodes/{NODE}/disks/smart?disk=/dev/sda": {
            "health": "PASSED",
            "type": "ata",
            "attributes": [
                {"id": "9", "name": "Power_On_Hours", "raw": "12345", "value": 99},
                {"id": "12", "name": "Power_Cycle_Count", "raw": "321", "value": 99},
                {"id": "194", "name": "Temperature_Celsius", "raw": "34", "value": 66},
            ],
        },
        f"nodes/{NODE}/disks/zfs": [
            {
                "name": "rpool",
                "health": "ONLINE",
                "size": 498_216_206_336,
                "alloc": 120_000_000_000,
                "free": 378_216_206_336,
                "frag": 5,
                "dedup": 1.0,
            }
        ],
        f"nodes/{NODE}/storage?storage=local": [
            {
                "storage": "local",
                "type": "dir",
                "content": "backup,iso,vztmpl",
                "active": 1,
                "enabled": 1,
                "shared": 0,
                "avail": 86_466_027_520,
                "used": 14_395_699_200,
                "total": 100_861_726_720,
                "used_fraction": 0.1427,
            }
        ],
        f"nodes/{NODE}/storage?storage=ext": [
            {
                "storage": "ext",
                "type": "nfs",
                "content": "backup,images",
                "active": 1,
                "enabled": 1,
                "shared": 1,
                "avail": 57_080_139_776,
                "used": 414_336_409_600,
                "total": 471_416_549_376,
                "used_fraction": 0.8789,
            }
        ],
        f"nodes/{NODE}/qemu/101/status/current": qemu_status(101, "vm-test-101"),
        f"nodes/{NODE}/qemu/101/agent/get-fsinfo": {
            "result": [
                {
                    "name": "sda1",
                    "mountpoint": "/",
                    "type": "ext4",
                    "used-bytes": 12_000_000_000,
                    "total-bytes": 33_000_000_000,
                    "disk": [
                        {"dev": "/dev/sda1", "bus-type": "scsi", "pci-controller": {}}
                    ],
                }
            ]
        },
        f"nodes/{NODE}/lxc/100/status/current": lxc_status(100, "lxc-test-100"),
    }


def add_guest(routes: dict[str, Any], kind: str, vmid: int, name: str) -> None:
    """Make a new VM (`qemu`) or container (`lxc`) appear in the route table."""
    resource = guest_resource(kind, vmid, name)
    routes["cluster/resources"].append(resource)
    routes[f"nodes/{NODE}/{kind}"].append(resource)
    status = qemu_status if kind == "qemu" else lxc_status
    routes[f"nodes/{NODE}/{kind}/{vmid}/status/current"] = status(vmid, name)
    if kind == "qemu":
        routes[f"nodes/{NODE}/qemu/{vmid}/agent/get-fsinfo"] = ResourceException(
            500, "Internal Server Error", "QEMU guest agent is not running"
        )


def remove_guest(routes: dict[str, Any], kind: str, vmid: int) -> None:
    """Make a VM or container disappear from the route table."""
    routes["cluster/resources"] = [
        resource
        for resource in routes["cluster/resources"]
        if resource.get("vmid") != vmid
    ]
    routes[f"nodes/{NODE}/{kind}"] = [
        resource
        for resource in routes[f"nodes/{NODE}/{kind}"]
        if resource["vmid"] != vmid
    ]
    routes.pop(f"nodes/{NODE}/{kind}/{vmid}/status/current", None)
    routes.pop(f"nodes/{NODE}/qemu/{vmid}/agent/get-fsinfo", None)


class FakeProxmox:
    """Answers `ProxmoxResource._request` from a route table."""

    def __init__(self, routes: dict[str, Any] | None = None) -> None:
        """Start with the default routes unless given others."""
        self.routes = default_routes() if routes is None else routes
        self.calls: list[tuple[str, str, dict | None, dict | None]] = []

    def request(
        self,
        resource: Any,
        method: str,
        data: dict | None = None,
        params: dict | None = None,
    ) -> Any:
        """Answer one request the way the real API would, or refuse it."""
        url = resource._store["base_url"]  # noqa: SLF001
        path = url.split(API_ROOT, 1)[1] if API_ROOT in url else url
        self.calls.append((method, path, data, params))
        if method != "GET":
            return f"UPID:{NODE}:0000FFFF:0000FFFF:69554D00:{path.rsplit('/', 1)[-1]}::root@pam:"
        if path not in self.routes:
            msg = f"no fake route for GET {path}"
            raise ResourceException(404, "Not Found", msg)
        answer = self.routes[path]
        if isinstance(answer, Exception):
            raise answer
        return copy.deepcopy(answer)

    def paths(self, method: str = "GET") -> list[str]:
        """Return the paths requested with `method`, in order."""
        return [path for called, path, _, _ in self.calls if called == method]

    @contextmanager
    def patched(self) -> Iterator[FakeProxmox]:
        """Route every proxmoxer request here, and skip the login round-trip."""
        with (
            patch(
                "proxmoxer.ProxmoxResource._request",
                autospec=True,
                side_effect=self.request,
            ),
            patch(
                "proxmoxer.backends.https.ProxmoxHTTPAuth._get_new_tokens",
                return_value=None,
            ),
        ):
            yield self
