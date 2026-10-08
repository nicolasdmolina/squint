"""Turn per-token model numbers into the API result (docs/api-contract.md "Result") and the
batch-scoring row (docs/calibration-format.md section 2). The web app and `squint-score`
both go through `score_text` + `Analysis`."""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from functools import cached_property

import numpy as np

from .backend import PairBackend, PositionStats
from .calibration import Calibration, length_bucket
from .config import Limits
from .reasons import LABELS, explanation, reasons
from .textproc import (
    TextTokenizer,
    core_index,
    display_tokens,
    paragraph_spans,
    sentence_spans,
    utf16_map,
    word_spans,
)

SIGNAL_SCALE = 2.0  # nats: a token 2 nats more predictable than expected gets signal tanh(1) = 0.76
SMOOTH_SCALE = 1.0  # windowed averages vary less, so a smaller scale
SMOOTH_WEIGHTS = np.array([1.0, 2.0, 3.0, 4.0, 3.0, 2.0, 1.0])
MIN_SPAN_TOKENS = 8  # sentences/paragraphs with fewer scored tokens get lean "neutral"


class TextTooShortToScore(ValueError):
    pass


@dataclass
class ScoredText:
    text: str
    ids: list[int]
    offsets: list[tuple[int, int]]
    pos: PositionStats
    model_pair: dict


def score_text(text: str, tokenizer: TextTokenizer, backend: PairBackend) -> ScoredText:
    ids, offsets = tokenizer.encode(text)
    if len(ids) < 2:
        raise TextTooShortToScore("the text needs at least two tokens")
    pos = backend.score_ids(ids)
    pair = {"observer": backend.observer_label, "performer": backend.performer_label}
    return ScoredText(text=text, ids=ids, offsets=offsets, pos=pos, model_pair=pair)


def _r(x, nd=4):
    if x is None:
        return None
    x = float(x)
    return round(x, nd) if math.isfinite(x) else None


def segment_windows(n_words: int, window: int, stride: int) -> list[tuple[int, int]]:
    """Windows of `window` words every `stride` words; the last one is aligned to the end."""
    if n_words < window or window <= 0:
        return []
    out = [(s, s + window) for s in range(0, n_words - window + 1, max(1, stride))]
    if out[-1][1] < n_words:
        out.append((n_words - window, n_words))
    return out


class Analysis:
    def __init__(self, scored: ScoredText, calibration: Calibration, limits: Limits, tokenizer: TextTokenizer | None):
        self.s = scored
        self.text = scored.text
        self.cal = calibration
        self.limits = limits
        self.tokenizer = tokenizer
        self.pair = scored.model_pair
        self.u16 = utf16_map(self.text)
        self.words = word_spans(self.text)
        self.n_words = len(self.words)
        self.word_starts = [w[0] for w in self.words]
        self.groups = display_tokens(self.text, scored.offsets)
        self._aggregate_groups()

    # ---------------------------------------------------------------- per display token
    def _aggregate_groups(self) -> None:
        pos = self.s.pos
        n = len(self.groups)
        self.g_s = np.zeros(n)
        self.g_e = np.zeros(n)
        self.g_scored = np.zeros(n, dtype=bool)
        self.g_n = np.zeros(n, dtype=np.int64)  # scored model tokens in the group
        self.g_lead = np.full(n, -1, dtype=np.int64)  # model token giving rank/top
        for k, g in enumerate(self.groups):
            for t in range(g.first, g.stop):
                s, e = pos.surprise[t], pos.expected[t]
                if math.isfinite(s) and math.isfinite(e):
                    self.g_s[k] += s
                    self.g_e[k] += e
                    self.g_n[k] += 1
                    self.g_scored[k] = True
                    if self.g_lead[k] < 0:
                        self.g_lead[k] = t
        self.g_core = [core_index(self.text, g.start, g.end) for g in self.groups]
        self.g_word = np.array(
            [max(0, bisect.bisect_right(self.word_starts, c) - 1) for c in self.g_core], dtype=np.int64
        )
        self.cum_s = np.concatenate([[0.0], np.cumsum(self.g_s)])
        self.cum_e = np.concatenate([[0.0], np.cumsum(self.g_e)])
        self.cum_n = np.concatenate([[0], np.cumsum(self.g_n)])

    def span_score(self, lo: int, hi: int) -> float | None:
        e = self.cum_e[hi] - self.cum_e[lo]
        if hi <= lo or e <= 0:
            return None
        return float((self.cum_s[hi] - self.cum_s[lo]) / e)

    def span_scored(self, lo: int, hi: int) -> int:
        return int(self.cum_n[hi] - self.cum_n[lo])

    def words_in(self, start: int, end: int) -> int:
        return bisect.bisect_left(self.word_starts, end) - bisect.bisect_left(self.word_starts, start)

    # ---------------------------------------------------------------- global numbers
    @cached_property
    def score(self) -> float | None:
        return self.s.pos.reference_score()

    @cached_property
    def stats(self) -> dict:
        pos = self.s.pos
        mask = np.isfinite(pos.surprise)
        r = pos.rank[mask]
        exp_all = np.concatenate([pos.expected[np.isfinite(pos.expected)], [pos.last_expected]])
        spread = None
        sent_scores = [x["_score"] for x in self.sentences_raw if x["_score"] is not None and x["_n"] >= MIN_SPAN_TOKENS]
        if len(sent_scores) >= 2:
            spread = float(np.std(sent_scores))
        return {
            "top1_rate": _r(np.mean(r == 1)) if r.size else None,
            "top5_rate": _r(np.mean(r <= 5)) if r.size else None,
            "mean_surprise": _r(np.mean(pos.surprise[mask])) if r.size else None,
            "mean_expected_surprise": _r(np.mean(exp_all)) if exp_all.size else None,
            "sentence_score_spread": _r(spread),
        }

    @cached_property
    def bucket(self) -> str:
        return length_bucket(self.n_words)

    @cached_property
    def thresholds(self) -> dict | None:
        return self.cal.bucket(self.bucket, self.pair)

    @cached_property
    def band(self) -> str:
        t, sc = self.thresholds, self.score
        if t is None or sc is None:
            return "uncalibrated"
        if sc < t["ai_below"]:
            return "likely_ai"
        if sc > t["human_above"]:
            return "likely_human"
        return "uncertain"

    def lean(self, score: float | None, n_scored: int, words: int) -> str:
        if score is None or n_scored < MIN_SPAN_TOKENS:
            return "neutral"
        t = self.cal.lean_thresholds(words, self.pair)
        if score < t["ai_below"]:
            return "ai"
        if score > t["human_above"]:
            return "human"
        return "neutral"

    # ---------------------------------------------------------------- sentences / paragraphs
    @cached_property
    def sentences_raw(self) -> list[dict]:
        text = self.text
        paras = paragraph_spans(text)
        sents = sentence_spans(text, paras)
        if not sents:
            sents = [(self.groups[0].start, self.groups[-1].end, 0)] if self.groups else []
            paras = [(sents[0][0], sents[0][1])] if sents else []
        starts = [s[0] for s in sents]
        assign = [max(0, bisect.bisect_right(starts, c) - 1) for c in self.g_core]
        used = sorted(set(assign))
        # sentences without any token are folded into a neighbour so token ranges stay contiguous
        merged: list[list] = []
        remap = {}
        for i, (s0, e0, p) in enumerate(sents):
            if i in used:
                remap[i] = len(merged)
                merged.append([s0, e0, p])
            elif merged:
                merged[-1][1] = max(merged[-1][1], e0)
        if used and used[0] > 0 and merged:
            merged[0][0] = sents[0][0]
        assign = [remap[a] for a in assign]
        out = []
        for i, (s0, e0, p) in enumerate(merged):
            toks = [k for k, a in enumerate(assign) if a == i]
            lo, hi = toks[0], toks[-1] + 1
            sc = self.span_score(lo, hi)
            out.append({"i": i, "_s": s0, "_e": e0, "token_start": lo, "token_end": hi, "_score": sc,
                        "_n": self.span_scored(lo, hi), "paragraph": p})
        # paragraphs that still own sentences, renumbered
        para_ids = sorted(set(x["paragraph"] for x in out))
        pmap = {p: j for j, p in enumerate(para_ids)}
        for x in out:
            x["paragraph"] = pmap[x["paragraph"]]
        self._para_spans = [paras[p] if p < len(paras) else None for p in para_ids]
        self._token_sentence = assign
        return out

    @cached_property
    def sentences(self) -> list[dict]:
        out = []
        for x in self.sentences_raw:
            words = self.words_in(x["_s"], x["_e"])
            out.append({
                "i": x["i"], "start": self.u16[x["_s"]], "end": self.u16[x["_e"]],
                "token_start": x["token_start"], "token_end": x["token_end"],
                "score": _r(x["_score"]), "lean": self.lean(x["_score"], x["_n"], words),
                "paragraph": x["paragraph"],
            })
        return out

    @cached_property
    def paragraphs(self) -> list[dict]:
        sents = self.sentences_raw
        out = []
        for j in range(len(self._para_spans)):
            members = [x for x in sents if x["paragraph"] == j]
            lo, hi = members[0]["token_start"], members[-1]["token_end"]
            s0 = min(x["_s"] for x in members)
            e0 = max(x["_e"] for x in members)
            sc = self.span_score(lo, hi)
            out.append({"i": j, "start": self.u16[s0], "end": self.u16[e0], "score": _r(sc),
                        "lean": self.lean(sc, self.span_scored(lo, hi), self.words_in(s0, e0))})
        return out

    # ---------------------------------------------------------------- segments
    def _segments(self, require_min_words: bool) -> list[dict]:
        if require_min_words and self.n_words < self.limits.percent_min_words:
            return []
        window, stride = self.cal.segment_params()
        out = []
        for ws, we in segment_windows(self.n_words, window, stride):
            lo = int(np.searchsorted(self.g_word, ws, side="left"))
            hi = int(np.searchsorted(self.g_word, we, side="left"))
            out.append({
                "start": self.u16[self.words[ws][0]], "end": self.u16[self.words[we - 1][1]],
                "word_start": ws, "word_end": we, "score": _r(self.span_score(lo, hi)),
            })
        return out

    @cached_property
    def segments(self) -> list[dict]:
        flag_below = self.cal.flag_below(self.pair)
        segs = self._segments(require_min_words=True)
        for seg in segs:
            seg["flagged"] = bool(flag_below is not None and seg["score"] is not None and seg["score"] < flag_below)
        return segs

    @cached_property
    def ai_percent(self) -> int | None:
        if not self.segments or self.cal.flag_below(self.pair) is None or self.n_words == 0:
            return None
        covered = np.zeros(self.n_words, dtype=bool)
        for seg in self.segments:
            if seg["flagged"]:
                covered[seg["word_start"]:seg["word_end"]] = True
        return int(round(100.0 * covered.sum() / self.n_words))

    # ---------------------------------------------------------------- tokens
    @cached_property
    def signal_center(self) -> float:
        t = self.cal.lean_thresholds(self.n_words, self.pair)
        return (t["ai_below"] + t["human_above"]) / 2.0

    def _signals(self) -> tuple[np.ndarray, np.ndarray]:
        c = self.signal_center
        d = np.where(self.g_scored, c * self.g_e - self.g_s, 0.0)
        sig = np.where(self.g_scored, np.tanh(d / SIGNAL_SCALE), 0.0)
        w = SMOOTH_WEIGHTS
        num = np.convolve(d, w, mode="same")
        den = np.convolve(self.g_scored.astype(float), w, mode="same")
        avg = np.divide(num, den, out=np.zeros_like(num), where=den > 0)
        smooth = np.tanh(avg / SMOOTH_SCALE)
        return sig, smooth

    @cached_property
    def tokens(self) -> list[dict]:
        _ = self.sentences_raw  # computes token -> sentence
        pos = self.s.pos
        sig, smooth = self._signals()
        out = []
        for k, g in enumerate(self.groups):
            lead = int(self.g_lead[k])
            top = []
            if lead >= 0 and self.tokenizer is not None:
                for tid, p in zip(pos.top_ids[lead], pos.top_p[lead]):
                    if tid >= 0:
                        top.append({"text": self.tokenizer.decode_token(int(tid)), "p": _r(p)})
            scored = bool(self.g_scored[k])
            out.append({
                "i": k, "start": self.u16[g.start], "end": self.u16[g.end], "text": self.text[g.start:g.end],
                "surprise": _r(self.g_s[k], 3) if scored else None,
                "expected_surprise": _r(self.g_e[k], 3) if scored else None,
                "signal": _r(sig[k], 3), "signal_smooth": _r(smooth[k], 3),
                "rank": int(pos.rank[lead]) if lead >= 0 else None,
                "top": top,
                "sentence": self._token_sentence[k],
            })
        return out

    # ---------------------------------------------------------------- outputs
    def verdict(self) -> dict:
        low = self.n_words < self.limits.percent_min_words
        score = self.score if self.score is not None else float("nan")
        return {
            "band": self.band,
            "label": LABELS[self.band],
            "confidence": "low" if low else "normal",
            "length_bucket": self.bucket,
            "score": _r(score),
            "thresholds": {k: _r(v) for k, v in self.thresholds.items()} if self.thresholds else None,
            "ai_percent": self.ai_percent,
            "explanation": explanation(self.band, score, self.thresholds, self.bucket, low),
        }

    def result(self) -> dict:
        return {
            "word_count": self.n_words,
            "token_count": len(self.s.ids),
            "model_pair": dict(self.pair),
            "verdict": self.verdict(),
            "reasons": reasons(self.stats, self.cal.medians(self.pair)),
            "stats": self.stats,
            "tokens": self.tokens,
            "sentences": self.sentences,
            "paragraphs": self.paragraphs,
            "segments": self.segments,
        }

    def batch_row(self, row_id) -> dict:
        segs = [{k: s[k] for k in ("word_start", "word_end", "start", "end", "score")}
                for s in self._segments(require_min_words=False)]
        return {
            "id": row_id,
            "word_count": self.n_words,
            "token_count": len(self.s.ids),
            "score": _r(self.score),
            "stats": self.stats,
            "segments": segs,
            "model_pair": dict(self.pair),
        }
