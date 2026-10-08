import io
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from conftest import PAIR, FakeBackend, FakeTokenizer, thresholds, words
from squint.app import create_app
from squint.config import Limits


def make_client(settings, *, backend=None, factory=None, password=None, tick=0.02, **over):
    if over:
        settings = settings.with_overrides(**over)
    backends = []

    def default_factory():
        b = backend if backend is not None else FakeBackend()
        backends.append(b)
        return b

    app = create_app(settings, backend_factory=factory or default_factory, tokenizer=FakeTokenizer(),
                     password=password, job_tick_s=tick)
    client = TestClient(app)
    client.backends = backends
    client.svc = app.state.svc
    return client


def wait_job(client, job_id, statuses=("done", "error"), timeout=10.0, headers=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = client.get(f"/api/jobs/{job_id}", headers=headers)
        assert r.status_code == 200, r.text
        snap = r.json()
        if snap["status"] in statuses:
            return snap
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} never reached {statuses}: {snap}")


def wait_for(cond, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.01)
    return False


def analyze(client, text, **kw):
    return client.post("/api/analyze", json={"text": text}, **kw)


# ------------------------------------------------------------------------------------- session


def test_no_password_mode(settings):
    with make_client(settings) as c:
        assert c.get("/api/session").json() == {"authenticated": True, "password_required": False}
        assert c.post("/api/login", json={"password": "anything"}).status_code == 204
        assert c.get("/api/status").status_code == 200


def test_password_flow(settings):
    with make_client(settings, password="hunter2") as c:
        assert c.get("/api/session").json() == {"authenticated": False, "password_required": True}
        for path in ("/api/status", "/api/accuracy", "/api/jobs/j_x"):
            r = c.get(path)
            assert r.status_code == 401 and r.json()["error"]["code"] == "auth_required"
        assert analyze(c, words(30)).status_code == 401
        assert c.post("/api/extract", files={"file": ("a.txt", b"hello there")}).status_code == 401

        r = c.post("/api/login", json={"password": "wrong"})
        assert r.status_code == 401 and r.json()["error"]["code"] == "bad_password"
        r = c.post("/api/login", json={"password": "hunter2"})
        assert r.status_code == 204
        cookie = r.headers["set-cookie"].lower()
        assert "squint_session=" in cookie and "httponly" in cookie and "samesite=lax" in cookie
        assert "secure" not in cookie  # plain http on localhost
        assert c.get("/api/session").json()["authenticated"] is True
        assert c.get("/api/status").status_code == 200

        token = c.cookies.get("squint_session")
        c.cookies.set("squint_session", token[:-2] + ("AA" if token[-2:] != "AA" else "BB"))
        assert c.get("/api/status").status_code == 401
        c.cookies.set("squint_session", token)
        assert c.post("/api/logout").status_code == 204
        c.cookies.clear()
        assert c.get("/api/session").json()["authenticated"] is False


def test_cookie_is_secure_behind_https_proxy(settings):
    with make_client(settings, password="pw") as c:
        r = c.post("/api/login", json={"password": "pw"}, headers={"X-Forwarded-Proto": "https"})
        assert "secure" in r.headers["set-cookie"].lower()


def test_login_attempts_are_limited(settings):
    with make_client(settings, password="pw", login_max_failures=3) as c:
        ip = {"CF-Connecting-IP": "203.0.113.5"}
        for _ in range(3):
            assert c.post("/api/login", json={"password": "nope"}, headers=ip).status_code == 401
        r = c.post("/api/login", json={"password": "pw"}, headers=ip)  # even the right one
        assert r.status_code == 429
        body = r.json()["error"]
        assert body["code"] == "rate_limited" and body["retry_after_s"] > 0
        assert int(r.headers["retry-after"]) == body["retry_after_s"]
        # another client is unaffected
        assert c.post("/api/login", json={"password": "pw"}, headers={"CF-Connecting-IP": "198.51.100.7"}).status_code == 204


# ------------------------------------------------------------------------------------- analyze


def test_word_limits(settings):
    with make_client(settings) as c:
        r = analyze(c, words(19))
        assert r.status_code == 422 and r.json()["error"]["code"] == "too_short"
        assert analyze(c, words(20)).status_code == 202
        r = analyze(c, words(2501))
        assert r.status_code == 422 and r.json()["error"]["code"] == "too_long"
        assert analyze(c, words(2500)).status_code == 202
        r = analyze(c, " ".join(["x" * 2000] * 25))  # few words, too many characters
        assert r.status_code == 422 and r.json()["error"]["code"] == "too_long"


def test_bad_requests(settings):
    with make_client(settings) as c:
        r = c.post("/api/analyze", content=b"text=hello", headers={"Content-Type": "application/x-www-form-urlencoded"})
        assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"
        r = c.post("/api/analyze", content=b"{nope", headers={"Content-Type": "application/json"})
        assert r.status_code == 400
        r = c.post("/api/analyze", json={"text": 5})
        assert r.status_code == 400
        r = c.post("/api/analyze", json=["text"])
        assert r.status_code == 400
        r = c.get("/api/jobs/j_doesnotexist")
        assert r.status_code == 404 and r.json()["error"]["code"] == "job_not_found"
        r = c.get("/api/nothing-here")
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_analyze_end_to_end(settings):
    (settings.calibration_dir / "thresholds.json").write_text(json.dumps(thresholds()))
    with make_client(settings, backend=FakeBackend(1.5)) as c:
        r = analyze(c, words(200))
        assert r.status_code == 202
        body = r.json()
        assert body["job_id"].startswith("j_") and body["position"] == 0
        snap = wait_job(c, body["job_id"])
        assert snap["status"] == "done" and snap["error"] is None and snap["position"] == 0
        res = snap["result"]
        assert res["verdict"]["band"] == "likely_ai"
        assert res["verdict"]["ai_percent"] == 100
        assert res["model_pair"] == PAIR
        assert set(res["timing_ms"]) == {"queue", "load", "score"}
        assert r.headers["cache-control"] == "no-store"
        # the submitted text is dropped once scored
        assert c.svc.queue._jobs[body["job_id"]].text == ""


def test_analyze_rate_limit(settings):
    lim = Limits(checks_per_hour=3)
    with make_client(settings, limits=lim) as c:
        a = {"CF-Connecting-IP": "203.0.113.9"}
        assert analyze(c, words(5), headers=a).status_code == 422  # rejected input does not count
        for _ in range(3):
            assert analyze(c, words(25), headers=a).status_code == 202
        r = analyze(c, words(25), headers=a)
        assert r.status_code == 429
        err = r.json()["error"]
        assert err["code"] == "rate_limited" and 3500 <= err["retry_after_s"] <= 3600
        assert r.headers["retry-after"] == str(err["retry_after_s"])
        assert analyze(c, words(25), headers={"CF-Connecting-IP": "203.0.113.10"}).status_code == 202
        # without CF-Connecting-IP the socket address is the key
        assert analyze(c, words(25)).status_code == 202


def test_queue_order_and_positions(settings):
    gate = threading.Event()
    log = []
    backend = FakeBackend(gate=gate, log=log)
    with make_client(settings, backend=backend) as c:
        texts = [words(20 + i, word=f"t{i}x") for i in range(3)]
        ids = []
        for i, t in enumerate(texts):
            r = analyze(c, t)
            assert r.status_code == 202
            ids.append(r.json()["job_id"])
            if i == 0:
                wait_job(c, ids[0], statuses=("scoring",))
        assert [c.get(f"/api/jobs/{j}").json()["position"] for j in ids] == [0, 1, 2]
        assert [c.get(f"/api/jobs/{j}").json()["status"] for j in ids] == ["scoring", "queued", "queued"]
        st = c.get("/api/status").json()
        assert st["queue_length"] == 3 and st["model_state"] == "ready"
        gate.set()
        snaps = [wait_job(c, j) for j in ids]
        assert all(s["status"] == "done" for s in snaps)
        assert [len(x) for x in log] == [20, 21, 22]  # scored in submission order
        assert c.get("/api/status").json()["queue_length"] == 0


def test_loading_model_state(settings):
    load_gate = threading.Event()
    with make_client(settings, backend=FakeBackend(load_gate=load_gate)) as c:
        assert c.get("/api/status").json()["model_state"] == "unloaded"
        jid = analyze(c, words(25)).json()["job_id"]
        assert wait_job(c, jid, statuses=("loading_model",))["status"] == "loading_model"
        assert c.get("/api/status").json()["model_state"] == "loading"
        load_gate.set()
        snap = wait_job(c, jid)
        assert snap["status"] == "done"
        assert c.get("/api/status").json()["model_state"] == "ready"


def test_queue_full(settings):
    gate = threading.Event()
    with make_client(settings, backend=FakeBackend(gate=gate), max_queue=1) as c:
        first = analyze(c, words(25)).json()["job_id"]
        wait_job(c, first, statuses=("scoring",))
        assert analyze(c, words(25)).status_code == 202
        r = analyze(c, words(25))
        assert r.status_code == 503 and r.json()["error"]["code"] == "busy"
        gate.set()


def test_idle_unload_and_reload(settings):
    with make_client(settings, idle_unload_s=0.2) as c:
        jid = analyze(c, words(25)).json()["job_id"]
        assert wait_job(c, jid)["status"] == "done"
        b1 = c.backends[0]
        assert b1.loaded
        assert wait_for(lambda: c.get("/api/status").json()["model_state"] == "unloaded", timeout=5)
        assert b1.unload_calls == 1 and not b1.loaded
        assert c.svc.manager.unloads == 1
        jid = analyze(c, words(25)).json()["job_id"]
        snap = wait_job(c, jid)
        assert snap["status"] == "done"
        assert c.svc.manager.loads == 2
    assert c.svc.manager.state == "unloaded"  # shutdown unloads too


def test_results_expire(settings):
    with make_client(settings, result_ttl_s=0.2) as c:
        jid = analyze(c, words(25)).json()["job_id"]
        assert wait_job(c, jid)["status"] == "done"
        assert wait_for(lambda: c.get(f"/api/jobs/{jid}").status_code == 404, timeout=5)


def test_job_errors(settings):
    class Broken(FakeBackend):
        def score_ids(self, ids):
            raise RuntimeError("boom")

    def failing_factory():
        raise OSError("no model file")

    with make_client(settings, factory=failing_factory) as c:
        snap = wait_job(c, analyze(c, words(25)).json()["job_id"])
        assert snap["status"] == "error" and snap["error"]["code"] == "model_unavailable"
        assert c.get("/api/status").json()["model_state"] == "unloaded"
    with make_client(settings, backend=Broken()) as c:
        snap = wait_job(c, analyze(c, words(25)).json()["job_id"])
        assert snap["status"] == "error" and snap["error"]["code"] == "scoring_failed"
        # the worker survives a failed job
        c.backends[0].score_ids = FakeBackend.score_ids.__get__(c.backends[0])
        assert wait_job(c, analyze(c, words(25)).json()["job_id"])["status"] == "done"
    with make_client(settings, limits=Limits(max_tokens=10)) as c:
        snap = wait_job(c, analyze(c, words(25)).json()["job_id"])
        assert snap["error"]["code"] == "too_long"


# ------------------------------------------------------------------------------------- status / accuracy


def test_status_and_accuracy(settings):
    with make_client(settings) as c:
        st = c.get("/api/status").json()
        assert st == {
            "model_state": "unloaded", "queue_length": 0, "model_pair": PAIR,
            "calibration": {"version": None, "ready": False},
            "limits": {"min_words": 20, "percent_min_words": 150, "max_words": 2500, "checks_per_hour": 30},
        }
        r = c.get("/api/accuracy")
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_calibrated"

        report = {"version": "2026-10-07", "model_pair": PAIR, "held_out": {"human": 1, "ai": 2}}
        (settings.calibration_dir / "report.json").write_text(json.dumps(report))
        (settings.calibration_dir / "thresholds.json").write_text(json.dumps(thresholds()))
        assert c.get("/api/accuracy").json() == report
        assert c.get("/api/status").json()["calibration"] == {"version": "2026-10-07", "ready": True}

        other = thresholds(pair={"observer": "A", "performer": "B"})
        (settings.calibration_dir / "thresholds.json").write_text(json.dumps(other) + " ")
        assert c.get("/api/status").json()["calibration"] == {"version": "2026-10-07", "ready": False}


# ------------------------------------------------------------------------------------- extract


def _docx_bytes():
    import docx

    d = docx.Document()
    d.add_paragraph("First paragraph of the essay.")
    t = d.add_table(rows=1, cols=2)
    t.cell(0, 0).text = "cell one"
    t.cell(0, 1).text = "cell two"
    d.add_paragraph("Last paragraph — with “quotes”.")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _pdf_bytes(text: str | None):
    stream = f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET".encode() if text else b""
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


def upload(c, name, data):
    return c.post("/api/extract", files={"file": (name, data, "application/octet-stream")})


def test_extract_formats(settings):
    with make_client(settings) as c:
        r = upload(c, "essay.txt", "Café text with “quotes”.\r\n\r\n\r\n\r\nSecond   para.\n".encode())
        assert r.status_code == 200
        assert r.json() == {"text": "Café text with “quotes”.\n\nSecond   para.", "filename": "essay.txt", "word_count": 6}
        assert upload(c, "old.TXT", "caf\xe9 au lait".encode("cp1252")).json()["text"] == "café au lait"
        assert upload(c, "u16.txt", "hello wide world".encode("utf-16")).json()["text"] == "hello wide world"

        r = upload(c, "paper.docx", _docx_bytes())
        assert r.status_code == 200
        assert r.json()["text"] == ("First paragraph of the essay.\n\ncell one\tcell two\n\n"
                                    "Last paragraph — with “quotes”.")

        r = upload(c, "scan.pdf", _pdf_bytes("Hello from a PDF file"))
        assert r.status_code == 200, r.text
        assert "Hello from a PDF file" in r.json()["text"]
        assert r.json()["filename"] == "scan.pdf"


def test_extract_errors(settings):
    with make_client(settings, max_upload_bytes=2000) as c:
        for name, data in (("pic.png", b"\x89PNG...."), ("noext", b"hello"), ("bad.docx", b"not a zip"),
                           ("bad.pdf", b"hello world")):
            r = upload(c, name, data)
            assert r.status_code == 415 and r.json()["error"]["code"] == "unsupported_file", name
        r = upload(c, "big.txt", b"a " * 1100)  # over max_upload_bytes, under the body cap
        assert r.status_code == 413 and r.json()["error"]["code"] == "file_too_large"
        r = upload(c, "huge.txt", b"a " * 50_000)  # over the request body cap
        assert r.status_code == 413 and r.json()["error"]["code"] == "file_too_large"
        for name, data in (("empty.txt", b"   \n\n "), ("blank.pdf", _pdf_bytes(None))):
            r = upload(c, name, data)
            assert r.status_code == 422 and r.json()["error"]["code"] == "no_text_found", name
        r = c.post("/api/extract", files={"other": ("a.txt", b"hello")})
        assert r.status_code == 400
        r = c.post("/api/extract", json={"text": "x"})
        assert r.status_code == 415


# ------------------------------------------------------------------------------------- web UI


def test_static_files_and_spa_fallback(settings, tmp_path):
    with make_client(settings) as c:
        r = c.get("/")
        assert r.status_code == 404 and "not built" in r.text

    dist = settings.web_dist
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Squint</title>")
    (dist / "assets" / "app-123.js").write_text("console.log(1)")
    (dist / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("top secret")
    with make_client(settings) as c:
        for path in ("/", "/check/abc", "/accuracy"):
            r = c.get(path)
            assert r.status_code == 200 and "Squint" in r.text and r.headers["cache-control"] == "no-cache"
        r = c.get("/assets/app-123.js")
        assert r.status_code == 200 and "immutable" in r.headers["cache-control"]
        assert "javascript" in r.headers["content-type"]
        assert c.get("/favicon.svg").headers["content-type"].startswith("image/svg")
        assert c.get("/assets/missing.js").status_code == 404
        for path in ("/..%2Fsecret.txt", "/assets/..%2F..%2Fsecret.txt", "/%2e%2e/secret.txt"):
            r = c.get(path)
            assert "top secret" not in r.text
        r = c.get("/")
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["x-frame-options"] == "DENY"


# ------------------------------------------------------------------------------------- hardening


def test_junk_session_cookies_are_just_unauthenticated(settings):
    with make_client(settings, password="pw") as c:
        for raw in (b"squint_session=e30.\xe9", b"squint_session=e30.\xc3\xa9\xc3\xa9", b"squint_session=\xe9\xe9",
                    b"squint_session=..", b"squint_session=%ZZ.%ZZ"):
            h = {"Cookie": raw}
            r = c.get("/api/session", headers=h)
            assert r.status_code == 200 and r.json() == {"authenticated": False, "password_required": True}
            r = c.get("/api/status", headers=h)
            assert r.status_code == 401 and r.json()["error"]["code"] == "auth_required"


def test_lone_surrogate_password_is_just_wrong(settings):
    with make_client(settings, password="pw") as c:
        r = c.post("/api/login", content=b'{"password": "\\ud83d"}', headers={"Content-Type": "application/json"})
        assert r.status_code == 401 and r.json()["error"]["code"] == "bad_password"


def test_failed_logins_everywhere_slow_logins_down_but_never_lock_out(settings):
    with make_client(settings, password="pw", login_global_max_failures=5, login_global_delay_s=0.2) as c:
        for i in range(8):  # an attacker rotating addresses
            r = c.post("/api/login", json={"password": "nope"}, headers={"CF-Connecting-IP": f"198.51.100.{i}"})
            assert r.status_code == 401
        t0 = time.monotonic()
        r = c.post("/api/login", json={"password": "pw"}, headers={"CF-Connecting-IP": "203.0.113.77"})
        assert r.status_code == 204
        assert time.monotonic() - t0 >= 0.2  # slowed, not blocked


def test_ipv6_clients_are_limited_by_their_64(settings):
    with make_client(settings, password="pw", login_max_failures=3, limits=Limits(checks_per_hour=2)) as c:
        for i in range(3):  # rotating addresses inside one /64
            r = c.post("/api/login", json={"password": "nope"}, headers={"CF-Connecting-IP": f"2001:db8:1:2::{i + 1:x}"})
            assert r.status_code == 401
        r = c.post("/api/login", json={"password": "pw"}, headers={"CF-Connecting-IP": "2001:db8:1:2:ffff:ffff:ffff:ffff"})
        assert r.status_code == 429
        assert c.post("/api/login", json={"password": "pw"}, headers={"CF-Connecting-IP": "2001:db8:1:3::1"}).status_code == 204
        for i in range(2):
            assert analyze(c, words(25), headers={"CF-Connecting-IP": f"2001:db8:aa:bb::{i + 1}"}).status_code == 202
        r = analyze(c, words(25), headers={"CF-Connecting-IP": "2001:DB8:AA:BB:1234:5678:9abc:def0"})
        assert r.status_code == 429
        assert analyze(c, words(25), headers={"CF-Connecting-IP": "2001:db8:aa:bc::1"}).status_code == 202


def test_lone_surrogate_text_is_rejected_before_queueing(settings):
    with make_client(settings, limits=Limits(checks_per_hour=1)) as c:
        body = json.dumps({"text": words(25) + " \ud83d"})  # ASCII JSON with a \ud83d escape
        r = c.post("/api/analyze", content=body, headers={"Content-Type": "application/json"})
        assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"
        assert c.svc.queue._jobs == {}
        # a proper pair is fine, and the rejected request did not use up the hourly check
        jid = analyze(c, words(25) + " \U0001F600").json()["job_id"]
        assert wait_job(c, jid)["status"] == "done"


def test_accuracy_report_for_another_model_pair_is_not_served(settings):
    with make_client(settings) as c:
        (settings.calibration_dir / "thresholds.json").write_text(json.dumps(thresholds()))
        for report in ({"version": "1", "model_pair": {"observer": "A", "performer": "B"}},
                       {"version": "2", "model_pair": {"observer": PAIR["observer"], "performer": "B"}},
                       {"version": "3"}):
            (settings.calibration_dir / "report.json").write_text(json.dumps(report))
            r = c.get("/api/accuracy")
            assert r.status_code == 404 and r.json()["error"]["code"] == "not_calibrated", report
        good = {"version": "4", "model_pair": PAIR}
        (settings.calibration_dir / "report.json").write_text(json.dumps(good))
        assert c.get("/api/accuracy").json() == good


def test_require_password_refuses_to_start_without_one(settings, monkeypatch):
    import squint.app
    from squint.auth import PasswordMissing

    strict = settings.with_overrides(require_password=True)
    kw = dict(backend_factory=FakeBackend, tokenizer=FakeTokenizer())
    with pytest.raises(PasswordMissing, match="require_password"):
        create_app(strict, password=None, **kw)
    with pytest.raises(PasswordMissing):
        create_app(strict, password="", **kw)
    monkeypatch.setattr(squint.app, "read_keychain_password", lambda service: None)
    with pytest.raises(PasswordMissing):
        create_app(strict, **kw)  # password read from the (missing) Keychain item
    assert create_app(strict, password="pw", **kw).state.svc.password == "pw"
    assert create_app(settings, **kw).state.svc.password is None  # flag off: private mode, as before


def test_squint_server_exits_with_a_clear_message(settings, monkeypatch, tmp_path):
    import socket

    import squint.app
    from squint import cli

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setattr(squint.app, "read_keychain_password", lambda service: None)
    monkeypatch.setenv("SQUINT_PROFILE", "qwen2.5-0.5b-standin")
    monkeypatch.setenv("SQUINT_PORT", str(port))
    monkeypatch.setenv("SQUINT_CALIBRATION_DIR", str(tmp_path))
    monkeypatch.setenv("SQUINT_REQUIRE_PASSWORD", "1")
    with pytest.raises(SystemExit) as exc:
        cli.server_main([])
    assert "require_password" in str(exc.value) and "refusing to start" in str(exc.value)


def test_extract_rate_limit(settings):
    with make_client(settings, limits=Limits(extracts_per_hour=2)) as c:
        a = {"CF-Connecting-IP": "203.0.113.20"}

        def up(name, data, headers=a):
            return c.post("/api/extract", files={"file": (name, data, "application/octet-stream")}, headers=headers)

        assert up("a.txt", b"hello there").status_code == 200
        assert up("b.docx", b"not a zip").status_code == 415  # failed uploads count too
        r = up("c.txt", b"hello again")
        assert r.status_code == 429
        err = r.json()["error"]
        assert err["code"] == "rate_limited" and 3500 <= err["retry_after_s"] <= 3600 and "2 file uploads" in err["message"]
        assert r.headers["retry-after"] == str(err["retry_after_s"])
        assert up("d.txt", b"other client", headers={"CF-Connecting-IP": "203.0.113.21"}).status_code == 200


def test_one_extraction_at_a_time(settings, monkeypatch):
    import squint.app

    started, release = threading.Event(), threading.Event()
    real = squint.app.extract_text

    def gated(filename, data, max_bytes):
        if filename == "slow.txt":
            started.set()
            assert release.wait(10)
        return real(filename, data, max_bytes)

    monkeypatch.setattr(squint.app, "extract_text", gated)
    with make_client(settings, extract_wait_s=0.3) as c:
        first = {}
        t = threading.Thread(target=lambda: first.update(r=upload(c, "slow.txt", b"slow file text")))
        t.start()
        assert started.wait(5)
        t0 = time.monotonic()
        r = upload(c, "second.txt", b"second file")
        assert r.status_code == 503 and r.json()["error"]["code"] == "busy"
        assert 0.3 <= time.monotonic() - t0 < 3
        # a slot that frees up while a request is waiting is taken
        threading.Timer(0.1, release.set).start()
        r = upload(c, "third.txt", b"third file")
        assert r.status_code == 200 and r.json()["text"] == "third file"
        t.join(10)
        assert first["r"].status_code == 200 and first["r"].json()["text"] == "slow file text"


def test_shutdown_does_not_unload_under_a_running_job(settings):
    gate = threading.Event()
    backend = FakeBackend(gate=gate)
    with make_client(settings, backend=backend) as c:
        jid = analyze(c, words(25)).json()["job_id"]
        wait_job(c, jid, statuses=("scoring",))
        c.svc.queue.stop(join_timeout=0.2)  # the worker is still inside score_ids
        assert backend.unload_calls == 0 and backend.loaded and c.svc.manager.state == "ready"
        assert c.svc.manager.unload() is False  # busy: refused
        gate.set()
        assert wait_for(lambda: c.svc.queue._jobs[jid].status == "done")
        assert wait_for(lambda: not c.svc.manager._busy)
    assert backend.unload_calls == 1 and c.svc.manager.state == "unloaded"


def test_idle_unload_never_races_a_new_job(settings):
    unloading, finish_unload = threading.Event(), threading.Event()
    seen = []
    holder = {}

    class SlowUnload(FakeBackend):
        def unload(self):
            unloading.set()
            assert finish_unload.wait(10)
            super().unload()

    class Recording(FakeBackend):
        def load(self):
            seen.append(sorted(j.status for j in holder["c"].svc.queue._jobs.values() if j.finished is None))
            super().load()

    made = []

    def factory():
        made.append(SlowUnload() if not made else Recording())
        return made[-1]

    with make_client(settings, factory=factory, idle_unload_s=0.2) as c:
        holder["c"] = c
        assert wait_job(c, analyze(c, words(25)).json()["job_id"])["status"] == "done"
        assert unloading.wait(5)  # the janitor is now unloading the idle pair
        r = analyze(c, words(25))  # not blocked by the unload
        assert r.status_code == 202
        jid = r.json()["job_id"]
        time.sleep(0.1)
        assert c.get(f"/api/jobs/{jid}").json()["status"] == "queued"  # held until the unload is done
        finish_unload.set()
        assert wait_job(c, jid)["status"] == "done"
        assert seen == [["loading_model"]]
        assert made[0].unload_calls == 1 and c.svc.manager.loads == 2
