"""Real llama.cpp runs with the small stand-in pair (skipped when its files are absent)."""

import dataclasses

import numpy as np
import pytest

from squint.analysis import Analysis, score_text
from squint.calibration import Calibration
from squint.config import Limits, load_profiles
from squint.textproc import TextTokenizer

pytestmark = pytest.mark.model

PROFILE = load_profiles()[0].get("qwen2.5-0.5b-standin")
present = PROFILE is not None and all(
    __import__("os").path.exists(p) for p in (PROFILE.observer.path, PROFILE.performer.path, PROFILE.tokenizer.path))

TEXT = (
    "The mitochondria is often described as the powerhouse of the cell, because it produces most of the "
    "chemical energy needed to power the cell's biochemical reactions. My grandmother, who never finished "
    "school, used to say the same thing about her kitchen on Sundays — loud, hot, and smelling of burnt garlic. "
) * 3


@pytest.fixture(scope="module")
def pair():
    if not present:
        pytest.skip("stand-in model files not present")
    from squint.backend import LlamaCppPair

    p = LlamaCppPair(PROFILE)
    p.load()
    yield p
    p.unload()
    assert not p.loaded


@pytest.fixture(scope="module")
def tok():
    if not present:
        pytest.skip("stand-in model files not present")
    return TextTokenizer(PROFILE.tokenizer.path)


def test_scores_are_finite_and_plausible(pair, tok):
    ids, _ = tok.encode(TEXT)
    st = pair.score_ids(ids)
    assert np.isnan(st.surprise[0])
    assert np.isfinite(st.surprise[1:]).all() and np.isfinite(st.expected[1:]).all()
    assert (st.rank[1:] >= 1).all()
    assert (np.diff(st.top_p[1:], axis=1) <= 1e-6).all()  # top-5 sorted by probability
    score = st.reference_score()
    assert 0.2 < score < 2.0


def test_micro_batch_and_window_invariance(pair, tok):
    ids, _ = tok.encode(TEXT)
    base = pair.score_ids(ids)
    orig = pair.profile
    try:
        pair.profile = dataclasses.replace(orig, batch_tokens=13)
        small = pair.score_ids(ids)
        np.testing.assert_allclose(small.surprise[1:], base.surprise[1:], atol=0.05)
        assert small.reference_score() == pytest.approx(base.reference_score(), rel=5e-3)
        # windows: 64-token passes with 48 tokens of carried-over context
        pair.profile = dataclasses.replace(orig, overlap_tokens=48)
        ctx = pair.context_tokens
        pair.context_tokens = 64
        windowed = pair.score_ids(ids)
        pair.context_tokens = ctx
        assert np.isfinite(windowed.surprise[1:]).all()
        np.testing.assert_allclose(windowed.surprise[1:64], base.surprise[1:64], atol=0.05)
        assert windowed.reference_score() == pytest.approx(base.reference_score(), rel=0.1)
    finally:
        pair.profile = orig


def test_full_analysis_with_real_models(pair, tok):
    text = "“Quoted” text, café, emoji 🍕👍🏽 and CJK 中文.  " + TEXT
    scored = score_text(text, tok, pair)
    r = Analysis(scored, Calibration(None, None), Limits(), tok).result()
    u16 = text.encode("utf-16-le")
    for t in r["tokens"]:
        assert u16[2 * t["start"]:2 * t["end"]].decode("utf-16-le") == t["text"]
    assert r["verdict"]["band"] == "uncalibrated"
    assert r["model_pair"] == PROFILE.model_pair
    assert any(t["top"] for t in r["tokens"])
