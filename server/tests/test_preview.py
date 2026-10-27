import json
import tomllib

from conftest import thresholds, words
from fastapi.testclient import TestClient
from test_clf import FakeClassifier, _run, clf_cfg

from squint.app import create_app
from squint.config import DEFAULT_CONFIG, load_settings


def _preview_client(settings, clf, cfg=None, pair_loads=None):
    settings = settings.with_overrides(mode="preview")
    (settings.calibration_dir / "thresholds.json").write_text(json.dumps(thresholds()))
    if cfg is not False:
        (settings.calibration_dir / "classifier.json").write_text(json.dumps(cfg or clf_cfg()))

    def pair():
        pair_loads.append(1) if pair_loads is not None else None
        raise AssertionError("preview mode must never load the model pair")

    app = create_app(settings, backend_factory=pair, tokenizer=None, password=None, job_tick_s=0.02,
                     classifier_factory=lambda c: clf)
    return TestClient(app)


def test_preview_runs_the_classifier_without_the_pair(settings):
    clf, loads = FakeClassifier(default=0.1), []
    text = words(100) + " robot " + words(100, "w")
    with _preview_client(settings, clf, pair_loads=loads) as c:
        assert c.get("/api/status").json()["mode"] == "preview"
        snap = _run(c, text)
    assert snap["status"] == "done", snap
    r = snap["result"]
    assert loads == []
    assert r["verdict"]["band"] == "likely_ai" and r["verdict"]["detector"] == "classifier"
    assert r["tokens"] == [] and r["sentences"] == [] and r["paragraphs"] == []
    assert r["model_pair"] is None and r["token_count"] is None and r["verdict"]["score"] is None
    assert all(v is None for v in r["stats"].values())
    assert [x["kind"] for x in r["reasons"]] == ["detector"]
    flagged = [s for s in r["segments"] if s["flagged"]]
    assert flagged and all(s["score"] is None for s in r["segments"])
    assert all("robot" in text[s["start"]:s["end"]] for s in flagged)
    assert 0 < r["verdict"]["ai_percent"] <= 100


def test_preview_short_text_is_too_short(settings):
    with _preview_client(settings, FakeClassifier()) as c:
        r = _run(c, words(30))["result"]
    assert r["verdict"]["band"] == "too_short" and r["segments"] == [] and r["verdict"]["ai_percent"] is None


def test_preview_without_classifier_fails_the_job(settings):
    with _preview_client(settings, FakeClassifier(), cfg=False) as c:
        snap = _run(c, words(80))
    assert snap["status"] == "error" and snap["error"]["code"] == "model_unavailable"


def test_app_prefix_serves_the_web_ui(settings):
    dist = settings.web_dist
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>squint</html>")
    (dist / "assets" / "a.js").write_text("x")
    with _preview_client(settings, FakeClassifier()) as c:
        for path in ("/", "/app", "/app/", "/app/index.html"):
            assert c.get(path).text == "<html>squint</html>", path
        assert c.get("/app/assets/a.js").text == "x"


def test_preview_settings_replace_the_limits(monkeypatch):
    monkeypatch.setenv("SQUINT_MODE", "preview")
    s = load_settings()
    with open(DEFAULT_CONFIG, "rb") as fh:
        preview = tomllib.load(fh)["preview"]
    assert s.mode == "preview"
    assert s.limits.max_words == preview["max_words"] and s.limits.checks_per_hour == preview["checks_per_hour"]
    assert s.max_queue == preview["max_queue"]
    monkeypatch.setenv("SQUINT_MODE", "full")
    assert load_settings().limits.max_words == 2500


def test_preview_never_asks_for_a_password(settings):
    app = create_app(settings.with_overrides(mode="preview", require_password=True), backend_factory=None,
                     tokenizer=None, password="secret", classifier_factory=lambda c: FakeClassifier())
    with TestClient(app) as c:
        assert c.get("/api/session").json() == {"authenticated": True, "password_required": False}
