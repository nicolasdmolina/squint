import json

import pytest

import squint.backend
import squint.textproc
from conftest import FakeBackend, FakeTokenizer, thresholds, words
from squint import cli


@pytest.fixture
def score_env(tmp_path, monkeypatch):
    cfg = tmp_path / "squint.toml"
    cfg.write_text(
        '[models]\nprofile = "fake"\n\n'
        '[profiles.fake]\nobserver_label = "Fake observer"\nperformer_label = "Fake performer"\n'
        'observer = "obs.gguf"\nperformer = "perf.gguf"\ntokenizer = "tokenizer.json"\n'
    )
    cal = tmp_path / "calibration"
    cal.mkdir()
    (cal / "thresholds.json").write_text(json.dumps(thresholds()))
    monkeypatch.setenv("SQUINT_CONFIG", str(cfg))
    monkeypatch.setenv("SQUINT_CALIBRATION_DIR", str(cal))
    monkeypatch.delenv("SQUINT_PROFILE", raising=False)
    backends = []

    def make_pair(profile, **kw):
        b = FakeBackend(1.6)
        backends.append(b)
        return b

    monkeypatch.setattr(squint.backend, "LlamaCppPair", make_pair)
    monkeypatch.setattr(squint.textproc, "TextTokenizer", lambda path: FakeTokenizer())
    return tmp_path, backends


def write_rows(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_squint_score_and_resume(score_env):
    tmp, backends = score_env
    inp, out = tmp / "in.jsonl", tmp / "out.jsonl"
    rows = [
        {"id": "a", "text": words(200), "label": "human"},
        {"id": "b", "text": "Hi"},
        {"id": "c", "text": ""},
        {"id": "d", "text": words(60)},
    ]
    write_rows(inp, rows[:3])
    cli.score_main(["--in", str(inp), "--out", str(out)])
    got = read_rows(out)
    assert [r["id"] for r in got] == ["a", "b", "c"]
    a = got[0]
    assert set(a) == {"id", "word_count", "token_count", "score", "stats", "segments", "model_pair"}
    assert a["score"] == pytest.approx(0.8)
    assert [(s["word_start"], s["word_end"]) for s in a["segments"]] == [(0, 150), (50, 200)]
    assert a["model_pair"] == {"observer": "Fake observer", "performer": "Fake performer"}
    assert got[1]["error"] == "too_short" and got[1]["score"] is None
    assert got[2]["error"] == "missing_text"
    assert backends[0].unload_calls == 1

    # refuse to clobber, then resume after an interrupted write
    with pytest.raises(SystemExit):
        cli.score_main(["--in", str(inp), "--out", str(out)])
    with open(out, "a") as fh:
        fh.write('{"id": "d", "word_cou')  # truncated trailing line
    write_rows(inp, rows)
    cli.score_main(["--in", str(inp), "--out", str(out), "--resume"])
    got = read_rows(out)
    assert [r["id"] for r in got] == ["a", "b", "c", "d"]
    assert got[3]["word_count"] == 60 and got[3]["segments"] == []
    assert len(backends) == 2  # only the missing row was scored, by a fresh load

    # nothing left to do: the models are not even loaded
    cli.score_main(["--in", str(inp), "--out", str(out), "--resume"])
    assert len(backends) == 2

    cli.score_main(["--in", str(inp), "--out", str(out), "--overwrite", "--limit", "1"])
    assert [r["id"] for r in read_rows(out)] == ["a"]
