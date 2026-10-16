import importlib.util
import json
import random
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import PAIR, FakeBackend, FakeTokenizer, thresholds, words
from squint.analysis import Analysis, score_text
from squint.app import create_app
from squint.calibration import Calibration
from squint.clf import ClassifierHolder, chunk_token_ids, config_ok, weighted_mean
from squint.config import Limits

REPO = Path(__file__).resolve().parents[2]


def clf_cfg(**over):
    c = {
        "version": "2026-10-14", "run": "fake-run", "model": "answerdotai/ModernBERT-base",
        "path": "server/models/classifier/fake-run", "max_length": 512, "max_chunks": 8,
        "min_words": 50, "ai_above": 0.99, "human_below": 0.5,
        "held_out": {"false_flags": {"n": 1340, "flagged": 3, "rate": 0.0022}},
        "by_length": {
            "20-49": {"humans": 750, "false_flag": 0.029},
            "50-149": {"humans": 753, "false_flag": 0.004, "chatgpt": {"n": 351, "caught": 0.98, "called_human": 0.02},
                       "claude": {"n": 299, "caught": 0.85, "called_human": 0.127}},
            "150+": {"humans": 587, "false_flag": 0.0, "chatgpt": {"n": 256, "caught": 1.0, "called_human": 0.0},
                     "claude": {"n": 238, "caught": 0.94, "called_human": 0.05}},
        },
    }
    c.update(over)
    return c


class FakeClassifier:
    """P(AI) = 1.0 for any text containing the word "robot", else `default`."""

    def __init__(self, default=0.1):
        self.default = default
        self.calls = []
        self.loaded = False

    def load(self):
        self.loaded = True

    def unload(self):
        self.loaded = False

    def predict(self, texts):
        self.calls.append(list(texts))
        return [1.0 if "robot" in t else self.default for t in texts]


def analyse(text, clf, cfg=None, surprise=1.8):
    tok = FakeTokenizer()
    backend = FakeBackend(surprise)
    backend.load()
    cal = Calibration(thresholds(), None, cfg if cfg is not None else clf_cfg())
    return Analysis(score_text(text, tok, backend), cal, Limits(), tok, clf)


# ---------------------------------------------------------------------------- parity with training


def _load_textchunks():
    spec = importlib.util.spec_from_file_location("textchunks", REPO / "classifier" / "textchunks.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_chunking_matches_the_training_code():
    tc = _load_textchunks()
    rng = random.Random(0)
    for _ in range(300):
        ids = list(range(rng.randint(0, 5000)))
        body, mc = rng.choice([510, 100, 7]), rng.choice([None, 1, 4, 8])
        assert chunk_token_ids(ids, body, mc) == tc.chunk_token_ids(ids, body, mc)
    assert weighted_mean([0.2, 0.8], [1, 3]) == tc.weighted_mean([0.2, 0.8], [1, 3])


def test_config_ok():
    assert config_ok(clf_cfg())
    assert not config_ok(None)
    assert not config_ok({**clf_cfg(), "ai_above": "x"})
    assert not config_ok({**clf_cfg(), "human_below": 0.999, "ai_above": 0.99})
    assert not config_ok({k: v for k, v in clf_cfg().items() if k != "path"})


# ---------------------------------------------------------------------------- verdicts


@pytest.mark.parametrize("n,word,default,band", [
    (30, "robot", 0.1, "too_short"),
    (49, "word", 0.1, "too_short"),
    (60, "robot", 0.1, "likely_ai"),
    (60, "word", 0.1, "likely_human"),
    (60, "word", 0.7, "uncertain"),
    (200, "robot", 0.1, "likely_ai"),
    (200, "word", 0.1, "likely_human"),
])
def test_classifier_decides_the_band(n, word, default, band):
    a = analyse(words(n, word), FakeClassifier(default))
    v = a.verdict()
    assert v["band"] == band
    assert v["detector"] == "classifier"
    assert v["label"] and v["explanation"]
    assert v["classifier"]["min_words"] == 50
    assert (v["classifier"]["ai_probability"] is None) == (band == "too_short")
    json.dumps(a.result(), allow_nan=False)


def test_too_short_skips_the_model_and_explains_why():
    clf = FakeClassifier()
    a = analyse(words(30), clf)
    v = a.verdict()
    assert v["label"] == "Too short to tell"
    assert "50 words" in v["explanation"] and "3%" in v["explanation"]
    assert clf.calls == []


def test_explanations_quote_held_out_numbers():
    v = analyse(words(200, "robot"), FakeClassifier()).verdict()
    assert "none of 587" in v["explanation"]
    v = analyse(words(80, "robot"), FakeClassifier()).verdict()
    assert "0.4%" in v["explanation"] and "rough read" in v["explanation"]
    v = analyse(words(80), FakeClassifier()).verdict()
    assert "13% of Claude" in v["explanation"]


def test_binoculars_score_still_reported_but_does_not_decide():
    # surprise 1.2 -> Binoculars score 0.6, far into its AI band; the classifier says human
    a = analyse(words(200), FakeClassifier(0.1), surprise=1.2)
    v = a.verdict()
    assert v["score"] == pytest.approx(0.6)
    assert v["thresholds"] is not None
    assert v["band"] == "likely_human"


def test_segments_and_ai_percent_come_from_the_classifier():
    text = words(150) + " " + words(150, "robot")
    a = analyse(text, FakeClassifier(0.1))
    segs = a.segments
    assert segs and any(s["flagged"] for s in segs) and not all(s["flagged"] for s in segs)
    assert segs[0]["flagged"] is False and segs[-1]["flagged"] is True
    assert 40 <= a.ai_percent <= 75
    assert a.verdict()["band"] == "likely_ai"  # "robot" is in the full text


def test_detector_reason_comes_first():
    rs = analyse(words(200, "robot"), FakeClassifier()).result()["reasons"]
    assert rs[0]["kind"] == "detector" and rs[0]["weight"] == "strong"


@pytest.mark.parametrize("cfg", [None, {"bad": 1}])
def test_falls_back_to_binoculars_without_a_usable_config(cfg):
    tok = FakeTokenizer()
    backend = FakeBackend(1.2)
    backend.load()
    a = Analysis(score_text(words(200), tok, backend), Calibration(thresholds(), None, cfg), Limits(), tok,
                 FakeClassifier())
    v = a.verdict()
    assert v["detector"] == "binoculars" and v["band"] == "likely_ai" and v["classifier"] is None


def test_falls_back_without_a_loaded_classifier():
    v = analyse(words(200), None).verdict()
    assert v["detector"] == "binoculars"


# ---------------------------------------------------------------------------- holder


def test_holder_loads_once_and_reloads_on_new_version():
    made = []

    def factory(cfg):
        made.append(FakeClassifier())
        return made[-1]

    h = ClassifierHolder(REPO, factory)
    a = h.get(clf_cfg())
    assert a is h.get(clf_cfg()) and a.loaded and len(made) == 1
    b = h.get(clf_cfg(version="2026-10-20"))
    assert b is not a and not a.loaded and len(made) == 2
    h.unload()
    assert not b.loaded
    assert h.get(None) is None


def test_holder_does_not_retry_a_broken_model():
    calls = []

    def factory(cfg):
        calls.append(1)
        raise OSError("missing model files")

    h = ClassifierHolder(REPO, factory)
    assert h.get(clf_cfg()) is None and h.get(clf_cfg()) is None
    assert len(calls) == 1
    h2 = ClassifierHolder(REPO, factory)
    h2.get(clf_cfg())
    h2.get(clf_cfg(version="new"))
    assert len(calls) == 3


# ---------------------------------------------------------------------------- API


def _client(settings, clf, cfg=None, report=None):
    (settings.calibration_dir / "thresholds.json").write_text(json.dumps(thresholds()))
    if cfg is not False:
        (settings.calibration_dir / "classifier.json").write_text(json.dumps(cfg or clf_cfg()))
    if report:
        (settings.calibration_dir / "report.json").write_text(json.dumps(report))
    app = create_app(settings, backend_factory=lambda: FakeBackend(), tokenizer=FakeTokenizer(), password=None,
                     job_tick_s=0.02, classifier_factory=lambda c: clf)
    return TestClient(app)


def _run(c, text):
    jid = c.post("/api/analyze", json={"text": text}).json()["job_id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        snap = c.get(f"/api/jobs/{jid}").json()
        if snap["status"] in ("done", "error"):
            return snap
        time.sleep(0.01)
    raise AssertionError("job never finished")


def test_api_uses_the_classifier_and_unloads_it_with_the_pair(settings):
    clf = FakeClassifier()
    with _client(settings, clf) as c:
        st = c.get("/api/status").json()
        assert st["classifier"] == {"version": "2026-10-14", "ready": True, "min_words": 50}
        snap = _run(c, words(200, "robot"))
        assert snap["status"] == "done", snap
        assert snap["result"]["verdict"]["band"] == "likely_ai"
        assert snap["result"]["verdict"]["detector"] == "classifier"
        assert clf.loaded
        assert c.app.state.svc.manager.unload()
        assert not clf.loaded


def test_api_without_classifier_json(settings):
    with _client(settings, FakeClassifier(), cfg=False) as c:
        assert c.get("/api/status").json()["classifier"] == {"version": None, "ready": False, "min_words": None}
        snap = _run(c, words(200))
        assert snap["result"]["verdict"]["detector"] == "binoculars"


def test_accuracy_includes_classifier_numbers(settings):
    report = {"version": "2026-10-08", "model_pair": dict(PAIR), "held_out": {"human": 1, "ai": 1}}
    with _client(settings, FakeClassifier(), report=report) as c:
        r = c.get("/api/accuracy").json()
        assert r["classifier"]["min_words"] == 50
        assert r["classifier"]["by_length"]["150+"]["false_flag"] == 0.0
        assert "path" not in r["classifier"]
