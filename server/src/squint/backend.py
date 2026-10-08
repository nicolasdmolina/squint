"""Model backends: the observer/performer pair that produces per-position Binoculars numbers.

The reference implementation (github.com/ahans30/Binoculars, binoculars/detector.py + metrics.py)
runs both models over the same token ids and computes, for each position j (whose logits
predict token j+1):

  * performer NLL of the actual next token          -> `surprise` of token j+1
  * cross-entropy  -sum_v softmax(observer_j)[v] * log_softmax(performer_j)[v]
                                                     -> `expected_surprise` of token j+1

  score = mean(performer NLL over tokens 1..n-1) / mean(cross-entropy over positions 0..n-1)

Note the reference's x-ppl average includes the last position (it predicts past the end of
the text) and its ppl average does not; `PositionStats.reference_score()` keeps that exactly.

`LlamaCppPair` runs GGUF models through llama.cpp (Metal) and never materialises a full
(n_tokens x vocab) logits matrix: it decodes in micro-batches and reduces each batch's logits
to the handful of numbers the app needs before decoding the next one.
"""

from __future__ import annotations

import ctypes
import gc
import logging
import math
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Protocol, Sequence

import numpy as np

from .config import ModelProfile

log = logging.getLogger("squint.backend")

TOP_K = 5


@dataclass
class PositionStats:
    """Per-token numbers for one text of n model tokens.

    Index i refers to model token i. Token 0 has no preceding context and is unscored
    (NaN / 0), exactly as in the reference implementation.
    """

    surprise: np.ndarray  # (n,) float64, performer NLL of token i given tokens < i; NaN at 0
    expected: np.ndarray  # (n,) float64, observer-vs-performer cross-entropy at position i-1; NaN at 0
    rank: np.ndarray  # (n,) int32, 1-based rank of token i in the performer distribution; 0 at 0
    top_ids: np.ndarray  # (n, TOP_K) int32, performer's top guesses for token i; -1 at row 0
    top_p: np.ndarray  # (n, TOP_K) float32
    last_expected: float  # cross-entropy at the final position (predicts past the text)

    @property
    def n(self) -> int:
        return int(self.surprise.shape[0])

    def reference_score(self) -> float | None:
        """Binoculars score exactly as `Binoculars.compute_score` aggregates it."""
        if self.n < 2:
            return None
        ppl = float(np.mean(self.surprise[1:]))
        x_ppl = float((np.sum(self.expected[1:]) + self.last_expected) / self.n)
        if x_ppl <= 0:
            return None
        return ppl / x_ppl


class PairBackend(Protocol):
    observer_label: str
    performer_label: str

    def load(self) -> None: ...

    def unload(self) -> None: ...

    @property
    def loaded(self) -> bool: ...

    def score_ids(self, ids: Sequence[int]) -> PositionStats: ...


def reduce_logits(perf: np.ndarray, obs: np.ndarray, next_ids: np.ndarray | None, block: int = 128):
    """Reduce one micro-batch of logits (rows = positions) to Binoculars numbers.

    perf, obs: (b, V) float32 logits from performer and observer at the same positions.
    next_ids:  (b,) actual next token ids; -1 (or None for all rows) where there is no next token.
    Returns (xent[b], surprise[b], rank[b], top_ids[b, K], top_p[b, K]). Works through the rows
    in blocks so temporaries stay around 4 * block * V floats.
    """
    b = perf.shape[0]
    if next_ids is None:
        next_ids = np.full(b, -1, dtype=np.int64)
    outs = [_reduce_block(perf[i:i + block], obs[i:i + block], next_ids[i:i + block]) for i in range(0, b, block)]
    return tuple(np.concatenate([o[k] for o in outs]) for k in range(5))


def _load_vvexpf():
    """Apple Accelerate's vectorised expf (about 3x faster than np.exp here); None elsewhere."""
    if sys.platform != "darwin":
        return None
    try:
        lib = ctypes.CDLL("/System/Library/Frameworks/Accelerate.framework/Accelerate")
        fn = lib.vvexpf
    except (OSError, AttributeError):
        return None
    fn.restype = None
    fn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
    return fn


_VVEXPF = _load_vvexpf()


def exp_inplace(a: np.ndarray) -> np.ndarray:
    if _VVEXPF is not None and a.dtype == np.float32 and a.flags.c_contiguous and 0 < a.size < 2**31:
        n = ctypes.c_int(a.size)
        _VVEXPF(a.ctypes.data, a.ctypes.data, ctypes.byref(n))
    else:
        np.exp(a, out=a)
    return a


def _reduce_block(perf: np.ndarray, obs: np.ndarray, next_ids: np.ndarray):
    perf = np.ascontiguousarray(perf, dtype=np.float32)
    obs = np.ascontiguousarray(obs, dtype=np.float32)
    b, vocab = perf.shape
    rows = np.arange(b)

    # log-sum-exp of the performer logits: log_softmax(performer) = perf - lse
    pmax = perf.max(axis=1)
    tmp = np.subtract(perf, pmax[:, None])
    exp_inplace(tmp)
    lse = np.log(tmp.sum(axis=1).astype(np.float64)) + pmax.astype(np.float64)  # pairwise float32 sum

    # cross-entropy of the performer against softmax(observer):
    #   -sum_v p_obs[v] * (perf[v] - lse) = lse - sum_v p_obs[v] * perf[v]
    np.subtract(obs, obs.max(axis=1)[:, None], out=tmp)
    exp_inplace(tmp)
    z = tmp.sum(axis=1).astype(np.float64)
    dot = np.matmul(tmp[:, None, :], perf[:, :, None])[:, 0, 0].astype(np.float64)  # row-wise dot (BLAS)
    xent = lse - dot / z
    del tmp

    valid = next_ids >= 0
    tok = np.where(valid, next_ids, 0).astype(np.int64)
    actual = perf[rows, tok]
    surprise = np.where(valid, lse - actual.astype(np.float64), np.nan)
    rank = np.where(valid, 1 + (perf > actual[:, None]).sum(axis=1, dtype=np.int32), 0).astype(np.int32)

    top_ids = top_k_rows(perf, TOP_K).astype(np.int32)
    top_p = np.exp(np.take_along_axis(perf, top_ids, axis=1).astype(np.float64) - lse[:, None]).astype(np.float32)
    return xent, surprise, rank, top_ids, top_p


def top_k_rows(x: np.ndarray, k: int, block: int = 64) -> np.ndarray:
    """Column indices of the k largest values in each row, largest first, ties to the lower
    index (same as a stable argsort of -x).

    A full-row argpartition over a 65k-150k vocabulary is slow. Rows are cut into blocks of
    `block` columns instead: the k-th largest block maximum is at most the k-th largest value,
    so every top-k entry (ties included) lies in a block whose maximum reaches it.
    """
    b, vocab = x.shape
    k = min(k, vocab)
    if vocab <= 4 * block * k:
        cols = np.broadcast_to(np.arange(vocab), (b, vocab))
        order = np.lexsort((cols, -x), axis=1)[:, :k]
        return np.take_along_axis(cols, order, axis=1)
    nblk = -(-vocab // block)
    pad = nblk * block - vocab
    xb = x if not pad else np.concatenate([x, np.full((b, pad), -np.inf, dtype=x.dtype)], axis=1)
    bmax = xb.reshape(b, nblk, block).max(axis=2)
    kth = np.partition(bmax, nblk - k, axis=1)[:, nblk - k]
    out = np.empty((b, k), dtype=np.int64)
    offs = np.arange(block)
    for r in range(b):
        blocks = np.flatnonzero(bmax[r] >= kth[r])
        cols = (blocks[:, None] * block + offs).ravel()
        order = np.lexsort((cols, -xb[r, cols]))[:k]
        out[r] = cols[order]
    return out


def plan_windows(n: int, context: int, overlap: int) -> list[tuple[int, int, int]]:
    """Split n positions into forward passes that fit the context window.

    Returns (input_start, score_start, end): feed tokens [input_start, end) and keep logits for
    positions [score_start, end). Every position is scored exactly once; after the first window
    each one sees at least `overlap` tokens of preceding context.
    """
    if n <= 0:
        return []
    context = max(2, context)
    overlap = max(0, min(overlap, context - 1))
    windows = []
    end = min(n, context)
    windows.append((0, 0, end))
    while end < n:
        score_start = end
        input_start = score_start - overlap
        end = min(n, input_start + context)
        windows.append((input_start, score_start, end))
    return windows


def assemble(n: int, parts) -> PositionStats:
    """Turn per-position reductions (position j predicts token j+1) into per-token arrays."""
    xent_pos = np.full(n, np.nan)
    surprise = np.full(n, np.nan)
    rank = np.zeros(n, dtype=np.int32)
    top_ids = np.full((n, TOP_K), -1, dtype=np.int32)
    top_p = np.zeros((n, TOP_K), dtype=np.float32)
    for start, (x, s, r, ti, tp) in parts:
        stop = start + len(x)
        xent_pos[start:stop] = x
        # position j's prediction belongs to token j+1
        tok_lo, tok_hi = start + 1, min(stop + 1, n)
        cnt = tok_hi - tok_lo
        if cnt > 0:
            surprise[tok_lo:tok_hi] = s[:cnt]
            rank[tok_lo:tok_hi] = r[:cnt]
            top_ids[tok_lo:tok_hi, : ti.shape[1]] = ti[:cnt]
            top_p[tok_lo:tok_hi, : tp.shape[1]] = tp[:cnt]
    expected = np.full(n, np.nan)
    if n > 1:
        expected[1:] = xent_pos[:-1]
    last = float(xent_pos[-1]) if n else float("nan")
    return PositionStats(surprise, expected, rank, top_ids, top_p, last)


# --------------------------------------------------------------------------------------------
# llama.cpp backend


_backend_init_lock = threading.Lock()
_backend_initialised = False
_log_cb = None  # keep a reference so the ctypes callback is not garbage collected


def _init_llama_backend(verbose: bool) -> None:
    global _backend_initialised, _log_cb
    with _backend_init_lock:
        if _backend_initialised:
            return
        import llama_cpp.llama_cpp as L

        if not verbose:
            @L.llama_log_callback
            def _quiet(level, text, user_data):  # pragma: no cover - C callback
                if level == 3:  # GGML_LOG_LEVEL_ERROR
                    log.warning("llama.cpp: %s", (text or b"").decode("utf-8", "replace").rstrip())

            _log_cb = _quiet
            L.llama_log_set(_log_cb, ctypes.c_void_p(0))
        L.llama_backend_init()
        _backend_initialised = True


class _LlamaModel:
    """One GGUF model + context, driven through the raw llama.cpp C API."""

    def __init__(self, path: str, *, n_ctx: int, n_batch: int, gpu_layers: int, flash_attn: str):
        import llama_cpp.llama_cpp as L

        self.L = L
        self.path = path
        if not os.path.exists(path):
            raise FileNotFoundError(f"model file not found: {path}")
        mparams = L.llama_model_default_params()
        mparams.n_gpu_layers = gpu_layers
        self.model = L.llama_model_load_from_file(path.encode("utf-8"), mparams)
        if not self.model:
            raise RuntimeError(f"llama.cpp could not load {path}")
        self.vocab = L.llama_model_get_vocab(self.model)
        self.n_vocab = int(L.llama_vocab_n_tokens(self.vocab))
        self.n_ctx_train = int(L.llama_model_n_ctx_train(self.model))
        cparams = L.llama_context_default_params()
        cparams.n_ctx = n_ctx
        cparams.n_batch = n_batch
        cparams.n_ubatch = n_batch
        cparams.n_seq_max = 1
        cparams.embeddings = False
        cparams.no_perf = True
        cparams.flash_attn_type = {
            "auto": L.LLAMA_FLASH_ATTN_TYPE_AUTO,
            "on": L.LLAMA_FLASH_ATTN_TYPE_ENABLED,
            "off": L.LLAMA_FLASH_ATTN_TYPE_DISABLED,
        }.get(flash_attn, L.LLAMA_FLASH_ATTN_TYPE_AUTO)
        self.ctx = L.llama_init_from_model(self.model, cparams)
        if not self.ctx:
            L.llama_model_free(self.model)
            self.model = None
            raise RuntimeError(f"llama.cpp could not create a context for {path}")
        self.n_ctx = int(L.llama_n_ctx(self.ctx))
        self.n_batch = n_batch
        self.batch = L.llama_batch_init(n_batch, 0, 1)

    def token_text(self, token_id: int) -> bytes:
        return self.L.llama_vocab_get_text(self.vocab, token_id)

    def clear(self) -> None:
        mem = self.L.llama_get_memory(self.ctx)
        self.L.llama_memory_clear(mem, True)

    def decode(self, ids: Sequence[int], pos0: int, want_logits: Sequence[bool]) -> np.ndarray:
        """Decode ids at positions pos0.. and return logits rows for the flagged tokens."""
        L = self.L
        b = self.batch
        n = len(ids)
        b.n_tokens = n
        n_out = 0
        for i, tok in enumerate(ids):
            b.token[i] = tok
            b.pos[i] = pos0 + i
            b.n_seq_id[i] = 1
            b.seq_id[i][0] = 0
            flag = bool(want_logits[i])
            b.logits[i] = flag
            n_out += flag
        rc = L.llama_decode(self.ctx, b)
        if rc != 0:
            raise RuntimeError(f"llama_decode failed with code {rc}")
        if n_out == 0:
            return np.empty((0, self.n_vocab), dtype=np.float32)
        ptr = L.llama_get_logits(self.ctx)
        arr = np.ctypeslib.as_array(ptr, shape=(n_out, self.n_vocab))
        return np.array(arr, dtype=np.float32, copy=True)

    def close(self) -> None:
        L = self.L
        if getattr(self, "batch", None) is not None:
            L.llama_batch_free(self.batch)
            self.batch = None
        if getattr(self, "ctx", None):
            L.llama_free(self.ctx)
            self.ctx = None
        if getattr(self, "model", None):
            L.llama_model_free(self.model)
            self.model = None


class LlamaCppPair:
    """Observer + performer GGUF models sharing one vocabulary."""

    def __init__(self, profile: ModelProfile, *, verbose: bool = False):
        self.profile = profile
        self.observer_label = profile.observer_label
        self.performer_label = profile.performer_label
        self.verbose = verbose
        self._observer: _LlamaModel | None = None
        self._performer: _LlamaModel | None = None
        self.context_tokens = profile.context_tokens
        self.info: dict = {}

    @property
    def loaded(self) -> bool:
        return self._observer is not None and self._performer is not None

    def load(self) -> None:
        if self.loaded:
            return
        _init_llama_backend(self.verbose)
        p = self.profile
        t0 = time.perf_counter()
        observer = performer = None
        try:
            observer = _LlamaModel(p.observer_path, n_ctx=p.context_tokens, n_batch=p.batch_tokens,
                                   gpu_layers=p.gpu_layers, flash_attn=p.flash_attn)
            performer = _LlamaModel(p.performer_path, n_ctx=p.context_tokens, n_batch=p.batch_tokens,
                                    gpu_layers=p.gpu_layers, flash_attn=p.flash_attn)
            self._check_same_vocab(observer, performer)
        except Exception:
            for m in (observer, performer):
                if m is not None:
                    m.close()
            raise
        self.context_tokens = min(p.context_tokens, observer.n_ctx, performer.n_ctx,
                                  observer.n_ctx_train, performer.n_ctx_train)
        self._observer, self._performer = observer, performer
        self.info = {
            "n_vocab": observer.n_vocab,
            "n_ctx_train": min(observer.n_ctx_train, performer.n_ctx_train),
            "context_tokens": self.context_tokens,
            "load_s": round(time.perf_counter() - t0, 2),
        }
        log.info("loaded model pair %s / %s: %s", self.observer_label, self.performer_label, self.info)

    @staticmethod
    def _check_same_vocab(a: _LlamaModel, b: _LlamaModel) -> None:
        """Binoculars needs identical tokenizers (reference: utils.assert_tokenizer_consistency)."""
        if a.n_vocab != b.n_vocab:
            raise RuntimeError(f"observer/performer vocab sizes differ: {a.n_vocab} vs {b.n_vocab}")
        for i in range(a.n_vocab):
            if a.token_text(i) != b.token_text(i):
                raise RuntimeError(f"observer/performer vocabularies differ at token id {i}")

    def vocab_texts(self) -> list[bytes]:
        assert self._observer is not None
        return [self._observer.token_text(i) for i in range(self._observer.n_vocab)]

    def unload(self) -> None:
        for m in (self._observer, self._performer):
            if m is not None:
                m.close()
        self._observer = self._performer = None
        gc.collect()

    def score_ids(self, ids: Sequence[int]) -> PositionStats:
        if not self.loaded:
            raise RuntimeError("model pair is not loaded")
        obs, perf = self._observer, self._performer
        assert obs is not None and perf is not None
        ids = [int(t) for t in ids]
        n = len(ids)
        bad = [t for t in ids if t < 0 or t >= obs.n_vocab]
        if bad:
            raise ValueError(f"token id out of range for this model pair: {bad[0]}")
        parts = []
        for input_start, score_start, end in plan_windows(n, self.context_tokens, self.profile.overlap_tokens):
            obs.clear()
            perf.clear()
            pos = input_start
            while pos < end:
                stop = min(end, pos + self.profile.batch_tokens)
                chunk = ids[pos:stop]
                want = [p >= score_start for p in range(pos, stop)]
                lp = perf.decode(chunk, pos - input_start, want)
                lo = obs.decode(chunk, pos - input_start, want)
                first = max(pos, score_start)
                if lp.shape[0]:
                    nxt = np.array([ids[j + 1] if j + 1 < n else -1 for j in range(first, stop)], dtype=np.int64)
                    parts.append((first, reduce_logits(lp, lo, nxt)))
                del lp, lo
                pos = stop
        return assemble(n, parts)
