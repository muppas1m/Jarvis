"""
Authenticated dashboard telemetry (4.C.2).

Real VM stats straight from /proc + os.statvfs — no psutil dependency, no
per-request subprocess (matches app.documents.search._free_memory_mb). CPU% is a
delta between two /proc/stat samples; the rest are point reads. Plus the grouped
subsystem health for the HUD ring (delegated to app.api.health.health_groups).

Mounted on the PROTECTED tier — these reveal operational detail (memory, load,
subsystem names), so unlike the public /health they require auth.
"""
import os
import time
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.health import health_groups
from app.utils import runtime_stats
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["system"])

_GB = 1024**3


# CPU% needs a delta between two /proc/stat samples. We cache the last sample and
# each read returns the busy-fraction since the previous read (~the poll
# interval). Primed once at import so the first dashboard poll already has a
# baseline instead of returning null.
_last_cpu: Optional[tuple[int, int]] = None  # (busy, total) jiffies


def _read_cpu_pct() -> Optional[float]:
    global _last_cpu
    try:
        with open("/proc/stat") as fh:
            parts = fh.readline().split()  # cpu user nice system idle iowait irq softirq steal…
        vals = [int(x) for x in parts[1:]]
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)  # idle + iowait
        total = sum(vals)
        busy = total - idle
        prev, _last_cpu = _last_cpu, (busy, total)
        if prev is None:
            return None  # no baseline yet (first sample)
        d_busy, d_total = busy - prev[0], total - prev[1]
        if d_total <= 0:
            return None
        return round(100.0 * d_busy / d_total, 1)
    except Exception:  # noqa: BLE001 — telemetry must never raise
        return None


def _read_mem_mb() -> Optional[tuple[float, float]]:  # (used, total)
    try:
        info: dict[str, int] = {}
        with open("/proc/meminfo") as fh:
            for line in fh:
                key, _, rest = line.partition(":")
                info[key] = int(rest.split()[0])  # KB
        total = info["MemTotal"] / 1024
        avail = info.get("MemAvailable", info.get("MemFree", 0)) / 1024
        return (total - avail, total)
    except Exception:  # noqa: BLE001
        return None


def _read_disk_gb() -> Optional[tuple[float, float]]:  # (used, total)
    try:
        st = os.statvfs("/")
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        return ((total - free) / _GB, total / _GB)
    except Exception:  # noqa: BLE001
        return None


def _read_load() -> Optional[tuple[float, float, float]]:
    try:
        with open("/proc/loadavg") as fh:
            a, b, c = fh.readline().split()[:3]
        return (float(a), float(b), float(c))
    except Exception:  # noqa: BLE001
        return None


class SystemStats(BaseModel):
    cpu_pct: Optional[float]
    cpu_count: int
    mem_used_mb: Optional[float]
    mem_total_mb: Optional[float]
    disk_used_gb: Optional[float]
    disk_total_gb: Optional[float]
    load_1m: Optional[float]
    load_5m: Optional[float]
    load_15m: Optional[float]
    uptime_s: float
    session_turns: int
    today_turns: int


@router.get("/system", response_model=SystemStats)
async def system_stats() -> SystemStats:
    mem = _read_mem_mb()
    disk = _read_disk_gb()
    load = _read_load()
    stats = runtime_stats.get_stats()
    return SystemStats(
        cpu_pct=_read_cpu_pct(),
        cpu_count=os.cpu_count() or 1,
        mem_used_mb=round(mem[0]) if mem else None,
        mem_total_mb=round(mem[1]) if mem else None,
        disk_used_gb=round(disk[0], 1) if disk else None,
        disk_total_gb=round(disk[1], 1) if disk else None,
        load_1m=load[0] if load else None,
        load_5m=load[1] if load else None,
        load_15m=load[2] if load else None,
        uptime_s=stats["uptime_s"],
        session_turns=stats["session_turns"],
        today_turns=stats["today_turns"],
    )


@router.get("/system/health")
async def system_health() -> dict:
    """Grouped subsystem health for the HUD ring (master-facing groups)."""
    return await health_groups()


# Prime the CPU delta baseline at import so the first poll returns a real value.
_read_cpu_pct()
