import hashlib
import io
import json
import shutil
import tarfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient

from squint import desktop
from squint.app import create_app
from squint.config import DEFAULT_CONFIG, REPO_DIR, load_settings
from squint.desktop import Desktop, Download, Setup, fetch, setup_app

GiB = 2**30


class Files(BaseHTTPRequestHandler):
    files: ClassVar[dict[str, bytes]] = {}
    ranges = True
    seen: ClassVar[list] = []

    def do_GET(self):
        body = self.files.get(self.path)
        if body is None:
            self.send_error(404)
            return
        rng = self.headers.get("Range")
        self.seen.append((self.path, rng))
        if rng and self.ranges:
            start = int(rng.split("=")[1].rstrip("-"))
            self.send_response(206)
            body = body[start:]
        else:
            self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def http():
    Files.files, Files.ranges, Files.seen = {}, True, []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Files)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _item(tmp_path, url, body, sha=True):
    return Download("thing", url, tmp_path / "thing.bin", len(body), hashlib.sha256(body).hexdigest() if sha else None)


def test_fetch_resumes_a_partial_download(http, tmp_path):
    body = bytes(range(256)) * 9000
    Files.files["/f"] = body
    item = _item(tmp_path, http + "/f", body)
    item.part.write_bytes(body[:100_000])
    fetch(item, threading.Event())
    assert item.dest.read_bytes() == body and not item.part.exists()
    assert Files.seen == [("/f", "bytes=100000-")]


def test_fetch_starts_over_when_the_server_ignores_range(http, tmp_path):
    body = b"abc" * 50_000
    Files.files["/f"], Files.ranges = body, False
    item = _item(tmp_path, http + "/f", body)
    item.part.write_bytes(b"zzz" * 1000)  # stale bytes that must not survive
    fetch(item, threading.Event())
    assert item.dest.read_bytes() == body


def test_fetch_deletes_a_file_that_fails_its_checksum(http, tmp_path):
    Files.files["/f"] = b"x" * 5000
    item = Download("thing", http + "/f", tmp_path / "thing.bin", 5000, "0" * 64)
    with pytest.raises(OSError, match="checksum"):
        fetch(item, threading.Event())
    assert not item.part.exists() and not item.dest.exists()


def _classifier_tar(run="modernbert-test") -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in (("model.safetensors", b"weights"), ("config.json", b"{}")):
            info = tarfile.TarInfo(f"{run}/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _resources(tmp_path, http, version="2026-10-18", run="modernbert-test"):
    res = tmp_path / "Resources"
    (res / "calibration").mkdir(parents=True)
    shutil.copyfile(DEFAULT_CONFIG, res / "squint.toml")
    (res / "calibration" / "thresholds.json").write_text('{"version": "t"}')
    tar = _classifier_tar(run)
    Files.files[f"/clf-{version}.tar.gz"] = tar
    cfg = {"version": version, "path": f"models/classifier/{run}", "ai_above": 0.9, "human_below": 0.1,
           "min_words": 50, "max_length": 512, "max_chunks": 8}
    manifest = {"classifier": {"version": version, "url": f"{http}/clf-{version}.tar.gz", "bytes": len(tar),
                               "sha256": hashlib.sha256(tar).hexdigest(), "config": cfg}}
    (res / "manifest.json").write_text(json.dumps(manifest))
    Files.files["/manifest.json"] = json.dumps(manifest).encode()
    return res


def _desk(tmp_path, http, memory=8 * GiB):
    return Desktop(tmp_path / "Resources", data=tmp_path / "data", memory=memory, manifest_url=http + "/manifest.json")


def _run_setup(setup, accept_update=False):
    setup.start(accept_update=accept_update)
    assert setup.finished.wait(10), setup.snapshot()


def test_first_run_installs_the_classifier_and_skips_the_pair_under_16_gb(http, tmp_path):
    _resources(tmp_path, http)
    desk = _desk(tmp_path, http)
    desk.prepare()
    assert (desk.calibration_dir / "thresholds.json").exists()
    plan = desk.plan()
    assert plan.first_run and plan.classifier and not plan.pair
    assert [d.label for d in plan.downloads] == ["Detector (2026-10-18)"]
    _run_setup(Setup(desk, plan))
    cfg = json.loads((desk.calibration_dir / "classifier.json").read_text())
    assert Path(cfg["path"]).is_absolute() and (Path(cfg["path"]) / "model.safetensors").read_bytes() == b"weights"
    assert desk.installed_classifier() == "2026-10-18"
    assert not list((desk.data / "downloads").iterdir())  # the archive is removed once unpacked
    assert desk.env()["SQUINT_MODE"] == "preview" and not desk.plan().needed


def test_pair_files_resolve_under_the_data_dir(http, tmp_path, monkeypatch):
    _resources(tmp_path, http)
    desk = _desk(tmp_path, http, memory=16 * GiB)
    monkeypatch.setenv("SQUINT_DATA_DIR", str(desk.data))
    profile = load_settings(desk.config_path).profile
    for f in (profile.observer, profile.performer, profile.tokenizer):
        assert Path(f.path).is_relative_to(desk.data)
        Path(f.path).parent.mkdir(parents=True, exist_ok=True)
        Path(f.path).write_bytes(b"x")
    assert desk.pair_downloads() == [] and desk.env()["SQUINT_MODE"] == "full"


def test_a_newer_classifier_is_offered_then_remembered_or_installed(http, tmp_path):
    _resources(tmp_path, http)
    desk = _desk(tmp_path, http)
    desk.prepare()
    _run_setup(Setup(desk, desk.plan()))
    _resources(tmp_path / "next", http, version="2026-11-02", run="modernbert-next")
    Files.files["/manifest.json"] = (tmp_path / "next" / "Resources" / "manifest.json").read_bytes()

    plan = desk.plan()
    assert plan.update == "2026-11-02" and not plan.needed  # asked, never downloaded unasked
    setup = Setup(desk, plan)
    setup.skip()
    assert setup.finished.is_set() and desk.plan().update is None

    desk.skip("older")
    setup = Setup(desk, desk.plan())
    _run_setup(setup, accept_update=True)
    assert desk.installed_classifier() == "2026-11-02"


def test_setup_reports_a_full_disk_without_downloading(http, tmp_path, monkeypatch):
    _resources(tmp_path, http)
    desk = _desk(tmp_path, http)
    setup = Setup(desk, desk.plan())
    monkeypatch.setattr(desktop.shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(10, 10, 5))
    setup.start()
    snap = setup.snapshot()
    assert snap["phase"] == "error" and snap["error"] == "disk" and snap["need_bytes"] > snap["free_bytes"]
    assert [p for p, _ in Files.seen if p != "/manifest.json"] == []


def test_setup_api_downloads_and_reports_progress(http, tmp_path):
    _resources(tmp_path, http)
    desk = _desk(tmp_path, http)
    setup = Setup(desk, desk.plan())
    with TestClient(setup_app(setup)) as c:
        assert "Set up Squint" in c.get("/").text
        assert c.get("/api/setup").json()["phase"] == "ask"
        c.post("/api/setup/start")
        deadline = time.time() + 10
        while c.get("/api/setup").json()["phase"] != "done":
            assert time.time() < deadline
            time.sleep(0.05)
        items = c.get("/api/setup").json()["items"]
    assert items and all(i["done"] == i["size"] for i in items)


def test_app_settings_use_app_limits_and_no_password(tmp_path, monkeypatch):
    monkeypatch.setenv("SQUINT_APP", "1")
    monkeypatch.setenv("SQUINT_MODE", "preview")
    monkeypatch.setenv("SQUINT_DATA_DIR", str(tmp_path))
    s = load_settings(DEFAULT_CONFIG)
    assert s.app and s.mode == "preview"
    assert s.limits.max_words == 2500 and s.limits.checks_per_hour == 10000  # [app], never [preview]
    assert s.profile.observer.path.startswith(str(tmp_path))
    s = s.with_overrides(calibration_dir=tmp_path, web_dist=tmp_path, require_password=True)
    app = create_app(s, backend_factory=lambda: None, tokenizer=None, password="secret", job_tick_s=0.02)
    with TestClient(app) as c:
        st = c.get("/api/status").json()
        assert st["app"] is True and c.get("/api/session").json()["password_required"] is False


def test_the_shipped_manifest_matches_the_promoted_classifier():
    man = json.loads((REPO_DIR / "mac" / "manifest.json").read_text())["classifier"]
    cfg = json.loads((REPO_DIR / "calibration" / "classifier.json").read_text())
    assert man["version"] == cfg["version"] and man["config"]["ai_above"] == cfg["ai_above"]
    assert man["url"].endswith(f"squint-classifier-{man['version']}.tar.gz") and len(man["sha256"]) == 64
