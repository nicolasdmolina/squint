"""Squint for Mac: the Python half of Squint.app (the Swift half is mac/Squint.swift).

The app starts `python -I -B -m squint.desktop --port N --resources <Contents/Resources>` and shows
http://127.0.0.1:N/ in its window. This module:

  1. when models are missing, or the manifest names a classifier newer than the installed one,
     serves a setup page (setup.html) that lists what will download, checks free disk, and
     downloads with progress, HTTP range resume and sha256 checks. An update is only offered:
     "Not now" remembers the version and the app starts with the classifier it has;
  2. then runs the normal server (create_app) with SQUINT_APP=1: full mode with the Binoculars
     pair on Macs with 16 GB of memory or more, the classifier alone (preview results) below that.

Everything downloaded lives in ~/Library/Application Support/Squint (SQUINT_APP_DATA):
  models/<profile>/...           the Binoculars pair and tokenizer, from Hugging Face
  models/classifier/<run>/       the trained classifier, from this repo's GitHub releases
  calibration/                   thresholds.json and report.json copied from the app, and
                                 classifier.json written when a classifier is installed
  state.json                     the classifier version the user said "Not now" to
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("squint.desktop")

MANIFEST_URL = "https://raw.githubusercontent.com/nicolasdmolina/squint/main/mac/manifest.json"
PAIR_MIN_MEMORY = 16 * 2**30  # a 16 GB Mac reports exactly this
EXTRACT_MARGIN = 2**30  # free space kept on top of what the downloads need
CHUNK = 1 << 20
USER_AGENT = "Squint-for-Mac"


def data_dir() -> Path:
    return Path(os.environ.get("SQUINT_APP_DATA") or Path.home() / "Library" / "Application Support" / "Squint")


def physical_memory() -> int:
    return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")


def _version_key(v: str) -> tuple:
    return tuple(int(p) if p.isdigit() else p for p in v.replace("-", ".").split("."))


# ------------------------------------------------------------------------------ downloads


@dataclass
class Download:
    label: str
    url: str
    dest: Path
    size: int
    sha256: str | None = None  # checked after the download when known
    done: int = 0

    @property
    def part(self) -> Path:
        return self.dest.with_name(self.dest.name + ".part")

    def remaining(self) -> int:
        if self.dest.exists():
            return 0
        have = self.part.stat().st_size if self.part.exists() else 0
        return max(0, self.size - have)


class Cancelled(Exception):
    pass


def fetch(item: Download, stop: threading.Event, on_progress=None, timeout: float = 30.0) -> None:
    """Download item.url to item.dest through item.part, resuming a partial .part with a Range
    request. A server that ignores Range (200) starts the file over. Raises Cancelled on stop."""
    item.dest.parent.mkdir(parents=True, exist_ok=True)
    have = item.part.stat().st_size if item.part.exists() else 0
    if item.size and have > item.size:
        item.part.unlink()
        have = 0
    if not item.size or have < item.size:
        req = urllib.request.Request(item.url, headers={"User-Agent": USER_AGENT})
        if have:
            req.add_header("Range", f"bytes={have}-")
        with urllib.request.urlopen(req, timeout=timeout) as res:
            if have and res.status != 206:
                have = 0
            item.done = have
            with open(item.part, "ab" if have else "wb") as out:
                while chunk := res.read(CHUNK):
                    if stop.is_set():
                        raise Cancelled()
                    out.write(chunk)
                    item.done += len(chunk)
                    if on_progress:
                        on_progress()
    item.done = item.part.stat().st_size
    if item.size and item.done != item.size:
        raise OSError(f"{item.label}: got {item.done} of {item.size} bytes")
    if item.sha256:
        h = hashlib.sha256()
        with open(item.part, "rb") as fh:
            while chunk := fh.read(8 * CHUNK):
                if stop.is_set():
                    raise Cancelled()
                h.update(chunk)
        if h.hexdigest() != item.sha256:
            item.part.unlink()
            item.done = 0
            raise OSError(f"{item.label} didn't match its checksum, so it was deleted. Try again.")
    os.replace(item.part, item.dest)


# ------------------------------------------------------------------------------ what to download


@dataclass
class Plan:
    downloads: list[Download] = field(default_factory=list)
    classifier: dict | None = None  # manifest entry to install, when one is downloading
    update: str | None = None  # a newer classifier version that is only offered
    first_run: bool = False  # nothing usable installed yet
    pair: bool = True  # this Mac runs the Binoculars pair

    @property
    def needed(self) -> bool:
        return bool(self.downloads)


class Desktop:
    def __init__(self, resources: Path, data: Path | None = None, memory: int | None = None,
                 manifest_url: str | None = None):
        self.resources = Path(resources)
        self.data = Path(data or data_dir())
        self.memory = physical_memory() if memory is None else memory
        self.manifest_url = manifest_url or os.environ.get("SQUINT_MANIFEST_URL") or MANIFEST_URL
        self.config_path = self.resources / "squint.toml"

    # -- paths and state

    @property
    def calibration_dir(self) -> Path:
        return self.data / "calibration"

    @property
    def pair(self) -> bool:
        return self.memory >= PAIR_MIN_MEMORY

    def env(self) -> dict:
        return {"SQUINT_CONFIG": str(self.config_path), "SQUINT_DATA_DIR": str(self.data),
                "SQUINT_CALIBRATION_DIR": str(self.calibration_dir),
                "SQUINT_WEB_DIST": str(self.resources / "web"), "SQUINT_APP": "1",
                "SQUINT_MODE": "full" if self.pair else "preview", "SQUINT_REQUIRE_PASSWORD": "0"}

    def _state(self) -> dict:
        try:
            return json.loads((self.data / "state.json").read_text())
        except (OSError, ValueError):
            return {}

    def skip(self, version: str) -> None:
        self.data.mkdir(parents=True, exist_ok=True)
        (self.data / "state.json").write_text(json.dumps({**self._state(), "skipped_classifier": version}))

    def prepare(self) -> None:
        """Copy the pair's calibration out of the app, so an app update brings its own."""
        self.calibration_dir.mkdir(parents=True, exist_ok=True)
        for name in ("thresholds.json", "report.json"):
            src = self.resources / "calibration" / name
            if src.exists():
                shutil.copyfile(src, self.calibration_dir / name)

    def installed_classifier(self) -> str | None:
        try:
            cfg = json.loads((self.calibration_dir / "classifier.json").read_text())
        except (OSError, ValueError):
            return None
        if not (Path(cfg.get("path", "")) / "model.safetensors").exists():
            return None
        return cfg.get("version")

    def manifest(self) -> dict:
        """The published manifest, or the copy the app shipped with when it can't be reached."""
        try:
            req = urllib.request.Request(self.manifest_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=4) as res:
                data = json.load(res)
            if isinstance(data.get("classifier"), dict):
                return data
        except (OSError, ValueError) as exc:
            log.info("manifest unreachable (%s); using the bundled copy", exc)
        return json.loads((self.resources / "manifest.json").read_text())

    def pair_downloads(self) -> list[Download]:
        if not self.pair:
            return []
        os.environ["SQUINT_DATA_DIR"] = str(self.data)
        from huggingface_hub import get_hf_file_metadata, hf_hub_url

        from .config import load_settings

        profile = load_settings(self.config_path).profile
        items = []
        for role, f in ((profile.observer_label, profile.observer), (profile.performer_label, profile.performer),
                        ("Tokenizer", profile.tokenizer)):
            if Path(f.path).exists():
                continue
            url = hf_hub_url(f.repo, f.filename, revision=f.revision)
            meta = get_hf_file_metadata(url)
            etag = (meta.etag or "").strip('"')
            items.append(Download(role, url, Path(f.path), int(meta.size or 0),
                                  etag if len(etag) == 64 else None))
        return items

    def plan(self, accept_update: bool = False) -> Plan:
        have = self.installed_classifier()
        plan = Plan(pair=self.pair, first_run=have is None)
        man = self.manifest()["classifier"]
        newer = have is not None and _version_key(man["version"]) > _version_key(have)
        if newer and not accept_update and self._state().get("skipped_classifier") != man["version"]:
            plan.update = man["version"]
        if have is None or (newer and accept_update):
            plan.classifier = man
            plan.downloads.append(Download(f"Detector ({man['version']})", man["url"],
                                           self.data / "downloads" / Path(man["url"]).name,
                                           int(man["bytes"]), man["sha256"]))
        plan.downloads += self.pair_downloads()
        return plan

    def install_classifier(self, entry: dict, archive: Path) -> None:
        root = self.data / "models" / "classifier"
        root.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive) as tar:
            tar.extractall(root, filter="data")
        cfg = dict(entry["config"])
        cfg["path"] = str(root / Path(cfg["path"]).name)
        self.calibration_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.calibration_dir / "classifier.json.tmp"
        tmp.write_text(json.dumps(cfg, indent=2))
        os.replace(tmp, self.calibration_dir / "classifier.json")
        archive.unlink()


# ------------------------------------------------------------------------------ setup page


class Setup:
    """The setup page's state machine: ask -> downloading -> done (or error -> ask again)."""

    def __init__(self, desktop: Desktop, plan: Plan):
        self.desktop = desktop
        self.plan = plan
        self.phase = "ask"
        self.error: str | None = None
        self.stop = threading.Event()
        self.finished = threading.Event()
        self.current: Download | None = None
        self._thread: threading.Thread | None = None

    def need_bytes(self) -> int:
        extract = int(self.plan.classifier["bytes"]) if self.plan.classifier else 0
        return sum(d.remaining() for d in self.plan.downloads) + extract + EXTRACT_MARGIN

    def snapshot(self) -> dict:
        self.desktop.data.mkdir(parents=True, exist_ok=True)
        return {
            "phase": self.phase,
            "error": self.error,
            "first_run": self.plan.first_run,
            "update": self.plan.update,
            "pair": self.plan.pair,
            "memory_gb": round(self.desktop.memory / 2**30),
            "need_bytes": self.need_bytes(),
            "free_bytes": shutil.disk_usage(self.desktop.data).free,
            "current": self.current.label if self.current else None,
            "items": [{"label": d.label, "size": d.size,
                       "done": d.size if d.dest.exists() else (d.done or (d.part.stat().st_size if d.part.exists() else 0))}
                      for d in self.plan.downloads],
        }

    def start(self, accept_update: bool = False) -> None:
        if self.phase == "downloading":
            return
        if accept_update or self.phase == "error":
            try:
                self.plan = self.desktop.plan(accept_update=accept_update or self.plan.classifier is not None)
            except Exception as exc:
                self._fail(exc)
                return
        if not self.plan.needed:
            self._done()
            return
        snap = self.snapshot()
        if snap["free_bytes"] < snap["need_bytes"]:
            self.phase, self.error = "error", "disk"
            return
        self.phase, self.error = "downloading", None
        self._thread = threading.Thread(target=self._run, name="squint-download", daemon=True)
        self._thread.start()

    def skip(self) -> None:
        if self.plan.update:
            self.desktop.skip(self.plan.update)
        if self.plan.first_run or any(not d.dest.exists() for d in self.plan.downloads):
            return  # nothing to fall back on: first run, or the pair is still missing
        self._done()

    def _run(self) -> None:
        try:
            for d in self.plan.downloads:
                self.current = d
                if not d.dest.exists():
                    fetch(d, self.stop)
            if self.plan.classifier:
                self.current = None
                self.phase = "installing"
                arch = next(d.dest for d in self.plan.downloads if d.url == self.plan.classifier["url"])
                self.desktop.install_classifier(self.plan.classifier, arch)
            self._done()
        except Cancelled:
            pass
        except Exception as exc:
            self._fail(exc)

    def _fail(self, exc: Exception) -> None:
        log.warning("setup failed: %s", exc)
        self.phase = "error"
        self.error = "network" if isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError)) else str(exc)

    def _done(self) -> None:
        self.phase = "done"
        self.current = None
        self.finished.set()


def setup_app(setup: Setup):
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse, JSONResponse

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    page = (Path(__file__).parent / "setup.html").read_text(encoding="utf-8")

    @app.get("/api/setup")
    def state():
        return JSONResponse(setup.snapshot(), headers={"cache-control": "no-store"})

    @app.post("/api/setup/start")
    def start(update: bool = False):
        setup.start(accept_update=update)
        return setup.snapshot()

    @app.post("/api/setup/skip")
    def skip():
        setup.skip()
        return setup.snapshot()

    @app.get("/{path:path}")
    def index(path: str):
        return HTMLResponse(page, headers={"cache-control": "no-store"})

    return app


# ------------------------------------------------------------------------------ main


def _watch_parent() -> None:
    """Exit when Squint.app goes away without stopping us (a crash or a force quit)."""
    parent = os.getppid()
    while True:
        time.sleep(2)
        if os.getppid() != parent:
            log.info("Squint.app is gone; exiting")
            os._exit(0)


def _serve(app, port: int, until: threading.Event | None = None) -> None:
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, workers=1, log_level="info"))
    if until is not None:
        def stop_when_done():
            until.wait()
            time.sleep(1.5)  # let the page see "done" before the port closes
            server.should_exit = True
        threading.Thread(target=stop_when_done, daemon=True).start()
    server.run()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="squint-desktop", description="Squint for Mac: setup, then the server.")
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--resources", type=Path, required=True, help="Squint.app/Contents/Resources")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    threading.Thread(target=_watch_parent, daemon=True).start()

    desk = Desktop(args.resources)
    desk.prepare()
    os.environ.update(desk.env())
    try:
        plan = desk.plan()
    except Exception as exc:  # offline on first run, or Hugging Face unreachable
        log.warning("could not plan downloads: %s", exc)
        plan = Plan(first_run=desk.installed_classifier() is None, pair=desk.pair)
        setup = Setup(desk, plan)
        setup._fail(exc)
    else:
        setup = Setup(desk, plan)
    if plan.needed or plan.update or setup.phase == "error":
        log.info("setup: %d downloads, update %s", len(plan.downloads), plan.update)
        _serve(setup_app(setup), args.port, until=setup.finished)
        if not setup.finished.is_set():
            return  # quit during setup

    from .app import create_app
    from .config import load_settings

    settings = load_settings(desk.config_path)
    log.info("starting Squint: mode=%s data=%s", settings.mode, desk.data)
    _serve(create_app(settings), args.port)


if __name__ == "__main__":
    main(sys.argv[1:])
