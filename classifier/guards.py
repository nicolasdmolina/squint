"""Window and yield-to-the-user guards for the nightly run (standard library only, unit-tested).

Pure functions take the clock / status / memory text as arguments so tests can drive them;
the probe_* helpers read the real machine.
"""

from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, time as dtime, timedelta


def parse_hhmm(s: str) -> dtime:
    h, m = s.strip().split(":")
    return dtime(int(h), int(m))


def window_bounds(now: datetime, start: str, end: str) -> tuple[datetime, datetime] | None:
    """The window (start, end) that contains `now`, or None when `now` is outside it.
    Windows may cross midnight (e.g. 23:00-06:00). start == end means no window."""
    s, e = parse_hhmm(start), parse_hhmm(end)
    if s == e:
        return None
    for day in (now.date() - timedelta(days=1), now.date()):
        ws = datetime.combine(day, s, tzinfo=now.tzinfo)
        we = datetime.combine(day if e > s else day + timedelta(days=1), e, tzinfo=now.tzinfo)
        if ws <= now < we:
            return ws, we
    return None


def seconds_left(now: datetime, start: str, end: str) -> float:
    """Seconds until the current window closes; 0 when outside the window."""
    b = window_bounds(now, start, end)
    return max(0.0, (b[1] - now).total_seconds()) if b else 0.0


def service_busy(status: dict | None) -> str | None:
    """Why the Squint service needs the machine, or None. An unreachable service (None) is not
    busy: nothing is loaded and nobody can be waiting on it."""
    if not status:
        return None
    if status.get("_timeout"):
        return "Squint did not answer /api/status in time (busy)"
    q = status.get("queue_length") or 0
    if q > 0:
        return f"Squint has {q} queued check(s)"
    state = status.get("model_state")
    if state in ("loading", "ready"):
        return f"Squint models are {state} (about 9 GB in memory)"
    return None


_FREE = re.compile(r"System-wide memory free percentage:\s*(\d+)%")


def memory_free_pct(memory_pressure_output: str) -> int | None:
    m = _FREE.search(memory_pressure_output or "")
    return int(m.group(1)) if m else None


def heavy_stage_blocker(status: dict | None, free_pct: int | None, min_free_pct: int,
                        disk_free_gb: float | None = None, min_disk_gb: float = 0.0,
                        busy_procs: list[str] | None = None) -> str | None:
    """Reason a heavy stage (training / evaluation) must wait, or None when it may run.
    busy_procs: running processes that also want the GPU/memory (e.g. a squint-score job)."""
    why = service_busy(status)
    if why:
        return why
    if busy_procs:
        return f"another heavy job is running: {busy_procs[0][:80]}"
    if free_pct is not None and free_pct < min_free_pct:
        return f"memory free {free_pct}% < {min_free_pct}%"
    if disk_free_gb is not None and disk_free_gb < min_disk_gb:
        return f"disk free {disk_free_gb:.1f} GB < {min_disk_gb:.0f} GB"
    return None


# --- probes (real machine) ----------------------------------------------------------------

def probe_status(url: str, timeout: float = 15.0) -> dict | None:
    """GET /api/status. Not listening -> None (not busy). No answer in time -> {"_timeout": True}
    (busy). A password-protected server answers 401, which says nothing about load: returned
    as {"_http_error": 401} and treated as not busy."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code}
    except urllib.error.URLError as e:
        if isinstance(e.reason, (TimeoutError, socket.timeout)):
            return {"_timeout": True}
        return None
    except (TimeoutError, socket.timeout):
        return {"_timeout": True}
    except Exception:
        return None


def probe_memory_free_pct() -> int | None:
    try:
        out = subprocess.run(["/usr/bin/memory_pressure", "-Q"], capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return None
    return memory_free_pct(out)


def probe_disk_free_gb(path: str) -> float:
    return shutil.disk_usage(path).free / 1e9


def probe_busy_processes(patterns: list[str], own_pids: set[int] | None = None) -> list[str]:
    """Command lines of running processes matching any pattern (pgrep -f), minus our own."""
    own = own_pids or set()
    found = []
    for pat in patterns:
        if not pat:
            continue
        try:
            out = subprocess.run(["/usr/bin/pgrep", "-lf", pat], capture_output=True, text=True, timeout=10).stdout
        except Exception:
            continue
        for line in out.splitlines():
            pid, _, cmd = line.strip().partition(" ")
            if pid.isdigit() and int(pid) not in own and "pgrep" not in cmd:
                found.append(cmd)
    return found
