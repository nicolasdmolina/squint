"""The Binoculars numbers, checked against a direct port of the reference implementation
(github.com/ahans30/Binoculars binoculars/metrics.py + detector.py)."""

import numpy as np
import pytest

from squint.backend import assemble, plan_windows, reduce_logits


def _log_softmax(x):
    x = x.astype(np.float64)
    m = x.max(axis=-1, keepdims=True)
    return x - m - np.log(np.exp(x - m).sum(axis=-1, keepdims=True))


def reference_binoculars(observer_logits, performer_logits, input_ids):
    """numpy port of Binoculars.compute_score for one unpadded text.

    ppl   = perplexity(encodings, performer_logits)
    x_ppl = entropy(observer_logits, performer_logits, encodings, pad_token_id)
    """
    # metrics.perplexity: CE of logits[:-1] against labels[1:], averaged over the tokens
    shifted = performer_logits[:-1]
    labels = input_ids[1:]
    nll = -_log_softmax(shifted)[np.arange(len(labels)), labels]
    ppl = nll.mean()
    # metrics.entropy: p = softmax(observer), CE(input=performer, target=p) at every position
    p_proba = np.exp(_log_softmax(observer_logits))
    ce = -(p_proba * _log_softmax(performer_logits)).sum(axis=-1)
    x_ppl = ce.mean()
    return ppl / x_ppl


def _random_case(rng, n, vocab):
    perf = rng.normal(0, 3, size=(n, vocab)).astype(np.float32)
    obs = (perf + rng.normal(0, 1, size=(n, vocab))).astype(np.float32)
    ids = rng.integers(0, vocab, size=n)
    return perf, obs, ids


def test_plan_windows_small_text_is_one_pass():
    assert plan_windows(0, 2048, 512) == []
    assert plan_windows(10, 2048, 512) == [(0, 0, 10)]
    assert plan_windows(2048, 2048, 512) == [(0, 0, 2048)]


@pytest.mark.parametrize("n,context,overlap", [
    (2049, 2048, 512), (5000, 2048, 512), (12000, 2048, 512), (100, 16, 4), (37, 8, 7), (50, 10, 0),
])
def test_plan_windows_scores_every_position_once(n, context, overlap):
    windows = plan_windows(n, context, overlap)
    scored = np.zeros(n, dtype=int)
    for i, (input_start, score_start, end) in enumerate(windows):
        assert 0 <= input_start <= score_start < end <= n
        assert end - input_start <= context
        if i:
            assert score_start - input_start == overlap
        scored[score_start:end] += 1
    assert (scored == 1).all()


def test_reduce_logits_matches_naive():
    rng = np.random.default_rng(0)
    perf, obs, ids = _random_case(rng, 9, 1000)
    nxt = ids.copy()
    nxt[-1] = -1
    xent, surprise, rank, top_ids, top_p = reduce_logits(perf, obs, nxt, block=4)
    lp = _log_softmax(perf)
    p = np.exp(_log_softmax(obs))
    np.testing.assert_allclose(xent, -(p * lp).sum(-1), rtol=1e-5)
    np.testing.assert_allclose(surprise[:-1], -lp[np.arange(8), ids[:-1]], rtol=1e-5)
    assert np.isnan(surprise[-1]) and rank[-1] == 0
    for j in range(8):
        assert rank[j] == 1 + (perf[j] > perf[j, ids[j]]).sum()
        order = np.argsort(-perf[j], kind="stable")[:5]
        assert list(top_ids[j]) == list(order)
        np.testing.assert_allclose(top_p[j], np.exp(lp[j, order]), rtol=1e-4)


@pytest.mark.parametrize("n,context,overlap,batch", [(40, 4096, 512, 512), (40, 4096, 512, 7), (40, 12, 5, 4)])
def test_assembled_score_equals_reference(n, context, overlap, batch):
    """Logits here do not depend on context, so any window/micro-batch plan must reproduce the
    reference score exactly; this checks the position -> token bookkeeping."""
    rng = np.random.default_rng(n + batch)
    perf, obs, ids = _random_case(rng, n, 500)
    parts = []
    for input_start, score_start, end in plan_windows(n, context, overlap):
        pos = input_start
        while pos < end:
            stop = min(end, pos + batch)
            first = max(pos, score_start)
            if stop > first:
                nxt = np.array([ids[j + 1] if j + 1 < n else -1 for j in range(first, stop)])
                parts.append((first, reduce_logits(perf[first:stop], obs[first:stop], nxt)))
            pos = stop
    st = assemble(n, parts)
    ref = reference_binoculars(obs, perf, ids)
    assert st.reference_score() == pytest.approx(ref, rel=1e-6)
    # per-token numbers line up with the token they describe
    lp = _log_softmax(perf)
    assert np.isnan(st.surprise[0]) and np.isnan(st.expected[0]) and st.rank[0] == 0
    np.testing.assert_allclose(st.surprise[1:], -lp[np.arange(n - 1), ids[1:]], rtol=1e-5)
    # Sum(surprise)/Sum(expected) over all tokens differs from the reference only by the extra
    # last-position term in x_ppl
    assert np.isfinite(st.last_expected)


def test_reference_score_needs_two_tokens():
    rng = np.random.default_rng(1)
    perf, obs, ids = _random_case(rng, 1, 50)
    st = assemble(1, [(0, reduce_logits(perf, obs, np.array([-1])))])
    assert st.reference_score() is None


@pytest.mark.parametrize("vocab", [3, 7, 1000, 1280, 1281, 5000, 65024])
def test_top_k_rows_matches_argsort(vocab):
    from squint.backend import top_k_rows

    rng = np.random.default_rng(vocab)
    x = rng.normal(size=(6, vocab)).astype(np.float32)
    x[0, :] = 0.0  # all ties: lowest indices win
    x[1, -3:] = 50.0  # the winners sit in the last (padded) block
    got = top_k_rows(x, 5)
    k = min(5, vocab)
    for row in range(6):
        assert list(got[row]) == list(np.argsort(-x[row], kind="stable")[:k])
