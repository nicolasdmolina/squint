"""Threshold fitting for the classifier and the Binoculars + classifier rule (stdlib, unit-tested).

Conventions:
  classifier probability p (AI-ness, 0..1): a text is flagged when p > t
  Binoculars score b (lower = more AI-like):  a text is flagged when b < b_cut
A false flag is a human text that gets flagged. The cap (default 1%) must hold for all human
texts AND for each named group (non-native writers); the strictest group decides.
"""

from __future__ import annotations

import math

NEG_INF = float("-inf")


def allowed(n: int, cap: float) -> int:
    """How many of n human texts may be flagged under the cap."""
    return math.floor(cap * n + 1e-9)


def cut_above(scores: list[float], k: int) -> float:
    """Lowest t with at most k scores strictly above it: the (k+1)-th largest score.
    No scores (or k >= n): -inf, nothing constrains t."""
    if k >= len(scores):
        return NEG_INF
    return sorted(scores, reverse=True)[k]


def fit_threshold(groups: dict[str, list[float]], cap: float) -> tuple[float, str]:
    """Classifier-only cutoff: the lowest t that keeps every group's false-flag rate <= cap.
    groups maps a name ("all", "non_native", ...) to that group's human p values.
    Returns (t, binding group name)."""
    best, bind = NEG_INF, None
    for name, scores in groups.items():
        if not scores:
            continue
        t = cut_above(scores, allowed(len(scores), cap))
        if bind is None or t > best:
            best, bind = t, name
    if bind is None:
        raise ValueError("no human scores to fit on")
    return best, bind


def flag_rate(scores: list[float], t: float) -> float:
    return sum(1 for s in scores if s > t) / len(scores) if scores else float("nan")


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def fit_or_rule(humans: list[dict], ais: list[dict], cap: float, groups=("non_native",)) -> dict:
    """Combined rule "flag if p > t OR b < b_cut", fitted to catch the most AI texts while every
    human group stays within the cap. humans/ais: dicts with p, b and subset. Candidate b_cut
    values are the lowest human Binoculars scores (cutting there can only spend the allowance);
    for each, t is the lowest value that keeps all groups within the cap.
    Returns {t, b_cut, catch, false_flags, binding}; b_cut = -inf means Binoculars adds nothing."""
    names = ["all", *groups]
    members = {"all": humans, **{g: [h for h in humans if h.get("subset") == g] for g in groups}}
    budget = min(allowed(len(members["all"]), cap), *(allowed(len(members[g]), cap) for g in groups if members[g]))
    hb = sorted({h["b"] for h in humans})
    cands = [NEG_INF] + hb[: budget + 1]
    best = None
    for bc in cands:
        t, bind, ok = NEG_INF, None, True
        for name in names:
            hs = members[name]
            if not hs:
                continue
            by_b = [h for h in hs if h["b"] < bc]
            extra = allowed(len(hs), cap) - len(by_b)
            if extra < 0:
                ok = False
                break
            rest = [h["p"] for h in hs if not h["b"] < bc]
            tg = cut_above(rest, extra)
            if bind is None or tg > t:
                t, bind = tg, name
        if not ok:
            continue
        catch = sum(1 for a in ais if a["p"] > t or a["b"] < bc) / len(ais) if ais else 0.0
        ff = sum(1 for h in humans if h["p"] > t or h["b"] < bc) / len(humans) if humans else 0.0
        cand = {"t": t, "b_cut": bc, "catch": catch, "false_flags": ff, "binding": bind}
        # most AI caught; on a tie, fewer human flags, then the classifier-only rule
        if best is None or (catch, -ff, bc == NEG_INF) > (best["catch"], -best["false_flags"], best["b_cut"] == NEG_INF):
            best = cand
    if best is None:
        raise ValueError("no feasible combined rule")
    return best


def apply_or_rule(p: float, b: float | None, rule: dict, t_classifier_only: float) -> bool:
    """Flag decision; texts without a Binoculars score fall back to the classifier-only cutoff."""
    if b is None:
        return p > t_classifier_only
    return p > rule["t"] or b < rule["b_cut"]
