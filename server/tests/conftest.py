from __future__ import annotations

import re
import threading
import zlib
from pathlib import Path

import numpy as np
import pytest

from squint.backend import TOP_K, PositionStats
from squint.config import Limits, ModelFile, ModelProfile, Settings

SERVER_DIR = Path(__file__).resolve().parents[1]
MODELS = SERVER_DIR / "models"
QWEN_TOKENIZER = MODELS / "qwen2.5-0.5b-standin" / "tokenizer.json"
FALCON_TOKENIZER = MODELS / "falcon-7b" / "tokenizer.json"

PAIR = {"observer": "Fake observer", "performer": "Fake performer"}


class FakeTokenizer:
    """Whitespace-ish tokenizer: each token is optional leading whitespace + a word."""

    def __init__(self):
        self._words: dict[int, str] = {}

    def encode(self, text):
        ids, offs = [], []
        for m in re.finditer(r"\s*\S+", text):
            word = m.group(0).strip()
            tid = 10 + zlib.crc32(word.encode()) % 50_000
            self._words[tid] = " " + word
            ids.append(tid)
            offs.append(m.span())
        return ids, offs

    def decode_token(self, tid):
        return self._words.get(int(tid), "?")

    def vocab(self):
        return {}


class FakeBackend:
    """Deterministic numbers: every scored token has the same surprise; expected is 2.0.
    So the Binoculars score of any text is exactly surprise / 2.0."""

    observer_label = PAIR["observer"]
    performer_label = PAIR["performer"]

    def __init__(self, surprise: float = 1.8, gate: threading.Event | None = None,
                 load_gate: threading.Event | None = None, log: list | None = None):
        self.surprise_value = surprise
        self.gate = gate
        self.load_gate = load_gate
        self.log = log if log is not None else []
        self._loaded = False
        self.load_calls = 0
        self.unload_calls = 0

    @property
    def loaded(self):
        return self._loaded

    def load(self):
        if self.load_gate is not None:
            assert self.load_gate.wait(10)
        self.load_calls += 1
        self._loaded = True

    def unload(self):
        self.unload_calls += 1
        self._loaded = False

    def score_ids(self, ids):
        assert self._loaded
        self.log.append(list(ids))
        if self.gate is not None:
            assert self.gate.wait(10)
        n = len(ids)
        if callable(self.surprise_value):
            s = np.array([float(self.surprise_value(i)) for i in range(n)])
        else:
            s = np.full(n, self.surprise_value, dtype=float)
        e = np.full(n, 2.0)
        s[0] = e[0] = np.nan
        rank = np.array([0] + [1 + (t % 7) for t in ids[1:]], dtype=np.int32)
        top_ids = np.tile(np.arange(10, 10 + TOP_K, dtype=np.int32), (n, 1))
        top_ids[0] = -1
        top_p = np.tile(np.array([0.4, 0.2, 0.1, 0.05, 0.05], dtype=np.float32), (n, 1))
        return PositionStats(s, e, rank, top_ids, top_p, 2.0)


def fake_profile(tokenizer_path: str = "/nonexistent/tokenizer.json") -> ModelProfile:
    return ModelProfile(
        name="fake",
        observer_label=PAIR["observer"],
        performer_label=PAIR["performer"],
        observer=ModelFile(path="/nonexistent/observer.gguf"),
        performer=ModelFile(path="/nonexistent/performer.gguf"),
        tokenizer=ModelFile(path=tokenizer_path),
    )


@pytest.fixture
def settings(tmp_path) -> Settings:
    (tmp_path / "calibration").mkdir()
    return Settings(
        profile=fake_profile(),
        limits=Limits(),
        calibration_dir=tmp_path / "calibration",
        web_dist=tmp_path / "web-dist",
        idle_unload_s=600,
        result_ttl_s=600,
    )


def words(n: int, word: str = "word") -> str:
    return " ".join(f"{word}{i}" for i in range(n))


def thresholds(pair=PAIR, **over):
    t = {
        "version": "2026-10-07",
        "model_pair": dict(pair),
        "buckets": {
            "20-49": {"ai_below": 0.70, "human_above": 1.00},
            "50-149": {"ai_below": 0.80, "human_above": 0.97},
            "150+": {"ai_below": 0.85, "human_above": 0.95},
        },
        "segment": {"window_words": 150, "stride_words": 75, "flag_below": 0.85},
        "medians": {
            "human": {"top1_rate": 0.38, "top5_rate": 0.66, "mean_surprise": 2.9, "sentence_score_spread": 0.11},
            "ai": {"top1_rate": 0.66, "top5_rate": 0.88, "mean_surprise": 1.8, "sentence_score_spread": 0.05},
        },
    }
    t.update(over)
    return t
