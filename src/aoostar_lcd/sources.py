"""Readers for host metrics (collector side). psutil first, Linux files where needed.

Every function either returns a value or raises; callers decide what a failure means.
"""

from __future__ import annotations

import fnmatch
import json
import os
import socket
import subprocess
from pathlib import Path

import psutil

ARCSTATS = Path("/proc/spl/kstat/zfs/arcstats")
SYS_NET = Path("/sys/class/net")
SYS_BLOCK = Path("/sys/block")
CPU_TEMP_CHIPS = ("k10temp", "coretemp", "zenpower", "cpu_thermal", "soc_thermal", "acpitz")
CHIP_LABELS = {
    "k10temp": "CPU",
    "coretemp": "CPU",
    "zenpower": "CPU",
    "cpu_thermal": "CPU",
    "nvme": "NVMe",
    "amdgpu": "GPU",
    "nouveau": "GPU",
    "acpitz": "ACPI",
    "drivetemp": "Disk",
}
# Interface name patterns that never carry "own" traffic (or would double count it).
VIRTUAL_IFACES = (
    "lo",
    "veth*",
    "docker*",
    "br-*",
    "virbr*",
    "vmbr*",
    "tap*",
    "fwbr*",
    "fwpr*",
    "fwln*",
    "tun*",
    "wg*",
    "zt*",
    "tailscale*",
    "bond*",
    "dummy*",
    "cni*",
    "flannel*",
)


def hostname() -> str:
    return socket.gethostname()


def boot_time() -> float:
    return psutil.boot_time()


def cpu_count() -> int | None:
    return psutil.cpu_count()


def load_average() -> list[float]:
    return [round(v, 2) for v in os.getloadavg()]


def cpu_busy_total() -> tuple[float, float]:
    """(busy, total) CPU seconds since boot, all cores. iowait counts as idle."""
    times = psutil.cpu_times()
    total = sum(times)
    idle = times.idle + getattr(times, "iowait", 0.0)
    return total - idle, total


def chip_temperature(chip: str, sensor: str | None = None, aggregate: str = "max") -> float | None:
    """Temperature in °C of a hwmon chip as psutil names it (k10temp, coretemp, nvme...).

    Several chips with the same name (two NVMe drives) are merged with ``aggregate``.
    """
    reader = getattr(psutil, "sensors_temperatures", None)
    if reader is None:
        return None
    readings = [
        entry.current
        for entry in reader().get(chip, [])
        if entry.current is not None and (sensor is None or entry.label == sensor)
    ]
    if not readings:
        return None
    if aggregate == "first":
        return round(readings[0], 1)
    if aggregate == "avg":
        return round(sum(readings) / len(readings), 1)
    return round(max(readings), 1)


def available_chips() -> list[str]:
    reader = getattr(psutil, "sensors_temperatures", None)
    return sorted(reader().keys()) if reader else []


def cpu_temperature(chip: str = "auto", sensor: str | None = None) -> float | None:
    chips = CPU_TEMP_CHIPS if chip == "auto" else (chip,)
    for name in chips:
        # The first reading of a CPU chip is the package/Tctl value.
        value = chip_temperature(name, sensor, "first" if sensor is None else "max")
        if value is not None:
            return value
    return None


def file_temperature(path: str, scale: float) -> float:
    with open(path, encoding="utf-8") as handle:
        return round(float(handle.read().strip()) * scale, 1)


def rotational_disks() -> list[str]:
    disks = []
    if not SYS_BLOCK.is_dir():
        return disks
    for dev in sorted(os.listdir(SYS_BLOCK)):
        if dev.startswith(("loop", "ram", "zram", "dm-", "md", "sr", "nbd")):
            continue
        try:
            if (SYS_BLOCK / dev / "queue" / "rotational").read_text().strip() == "1":
                disks.append(dev)
        except OSError:
            continue
    return disks


def smart_temperature(device: str, timeout: float = 20) -> float | None:
    """Drive temperature from ``smartctl --json``. Disks in standby are not woken up."""
    dev = device if device.startswith("/dev/") else f"/dev/{device}"
    result = subprocess.run(
        ["smartctl", "--json", "--nocheck=standby", "--attributes", dev],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    # smartctl's exit status is a bit mask; bit 1 = device open failed or in standby.
    try:
        data = json.loads(result.stdout or "{}")
    except ValueError:
        return None
    current = (data.get("temperature") or {}).get("current")
    return float(current) if isinstance(current, (int, float)) else None


def zfs_arc_bytes() -> int | None:
    if not ARCSTATS.exists():
        return None
    for line in ARCSTATS.read_text().splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "size":
            return int(parts[2])
    return None


def is_virtual_iface(name: str, patterns=VIRTUAL_IFACES) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def physical_interfaces(names, exclude=VIRTUAL_IFACES) -> list[str]:
    """Interfaces backed by a device (Linux), else those not matching ``exclude``."""
    names = sorted(names)
    if SYS_NET.is_dir():
        return [
            n
            for n in names
            if (SYS_NET / n / "device").exists() and not is_virtual_iface(n, exclude)
        ]
    return [n for n in names if not is_virtual_iface(n, exclude)]


def net_counters() -> dict[str, tuple[int, int]]:
    """{interface: (rx_bytes, tx_bytes)}."""
    return {
        name: (c.bytes_recv, c.bytes_sent)
        for name, c in psutil.net_io_counters(pernic=True).items()
    }


def run_command(argv: list[str], timeout: float) -> str:
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=True)
    return result.stdout


def zfs_pool(name: str, timeout: float = 30) -> dict:
    """Usable used/free bytes (``zfs list``) and health (``zpool list``) of a pool."""
    health = run_command(["zpool", "list", "-H", "-o", "health", name], timeout).strip()
    used, free = run_command(["zfs", "list", "-Hp", "-o", "used,avail", name], timeout).split()
    return {"used": int(used), "free": int(free), "total": int(used) + int(free), "health": health}


def mount_usage(path: str) -> dict:
    usage = psutil.disk_usage(path)
    return {
        "used": usage.used,
        "free": usage.free,
        "total": usage.used + usage.free,
        "health": None,
    }
