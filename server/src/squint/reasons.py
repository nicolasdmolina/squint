"""Plain-English verdict explanations and reasons. Templates over numbers; no LLM."""

from __future__ import annotations

LABELS = {
    "likely_human": "Likely human",
    "uncertain": "Uncertain",
    "likely_ai": "Likely AI",
    "uncalibrated": "Not tuned yet",
    "too_short": "Too short to tell",
}


def _share(x) -> str | None:
    """0.004 -> "0.4%", 0.127 -> "13%", 0 -> "none"."""
    if not isinstance(x, (int, float)):
        return None
    if x == 0:
        return "none"
    return f"{x * 100:.1f}%" if x < 0.01 else f"{round(x * 100)}%"


def classifier_explanation(band: str, cfg: dict, bucket: str, low_confidence: bool) -> str:
    """Verdict text when the trained classifier decides. Numbers come from classifier.json's
    held-out results for this length bucket, so the text says what testing showed."""
    stats = (cfg.get("by_length") or {}).get(bucket) or {}
    if band == "too_short":
        short = _share(((cfg.get("by_length") or {}).get("20-49") or {}).get("false_flag"))
        text = f"Squint needs at least {int(cfg['min_words'])} words to give a verdict."
        if short and short != "none":
            text += f" On shorter snippets its detector wrongly flagged about {short} of human writers in testing, which is too many."
        return text
    if band == "likely_ai":
        text = "Squint's detector, trained on human writing and on text from ChatGPT and Claude, says this reads like AI writing."
        ff = _share(stats.get("false_flag"))
        if ff == "none":
            text += f" In testing it flagged none of {stats.get('humans')} human texts of this length."
        elif ff:
            text += f" In testing it wrongly flagged {ff} of human texts of this length."
    elif band == "likely_human":
        text = "Squint's detector found no sign of AI writing."
        misses = [f"{_share(stats[g]['called_human'])} of {name} texts" for g, name in (("chatgpt", "ChatGPT"), ("claude", "Claude"))
                  if isinstance(stats.get(g), dict) and stats[g].get("called_human")]
        if misses:
            text += f" It still misses some: in testing on texts this long it called {' and '.join(misses)} human."
    else:
        text = "The detector's reading sits between its cutoffs for AI and human writing, so Squint won't call it either way."
    if low_confidence:
        text += " With fewer than 150 words, treat this as a rough read."
    return text


def classifier_reason(band: str, p: float | None, cfg: dict) -> dict:
    if p is None:
        return {"kind": "detector", "text": "The trained detector does not rate texts this short.", "weight": "weak"}
    side = {"likely_ai": "AI-like", "likely_human": "human-like"}.get(band, "in between")
    return {"kind": "detector",
            "text": f"A detector trained on ChatGPT and Claude writing rated this text {side}.",
            "weight": "weak" if band == "uncertain" else "strong"}


def explanation(band: str, score: float, thresholds: dict | None, bucket: str, low_confidence: bool) -> str:
    if band == "uncalibrated":
        text = (f"Squint hasn't been tuned for this model pair yet, so it gives no verdict. "
                f"The raw score is {score:.3f}; lower means more predictable, which is more AI-like.")
    elif band == "likely_ai":
        text = (f"The text was much more predictable than the models expected: its score of {score:.3f} is "
                f"below {thresholds['ai_below']:.3f}, a level few human texts of this length reached in tuning.")
    elif band == "likely_human":
        text = (f"The text was about as surprising to the models as human writing usually is: its score of "
                f"{score:.3f} is above {thresholds['human_above']:.3f}, where few AI texts of this length landed in tuning.")
    else:
        text = (f"The score of {score:.3f} sits between {thresholds['ai_below']:.3f} and "
                f"{thresholds['human_above']:.3f}, where human and AI texts overlap, so Squint won't call it either way.")
    if low_confidence:
        text += " With fewer than 150 words, treat this as a rough read."
    return text


def _pct(x: float) -> str:
    return f"{round(x * 100)}%"


_STATS = {
    # stat: (kind, sentence about the value, how to print a number)
    "top1_rate": ("predictability", "{v} of words and word pieces were the model's first guess.", _pct),
    "top5_rate": ("top_five", "{v} were among the model's top five guesses.", _pct),
    "mean_surprise": ("surprise", "Average surprise per token was {v} (lower means more predictable).", lambda x: f"{x:.2f}"),
    "sentence_score_spread": ("consistency", "Sentence-level scores varied by {v} from one sentence to the next.", lambda x: f"{x:.3f}"),
}


def reasons(stats: dict, medians: dict | None) -> list[dict]:
    """One reason per stat, compared against the calibration medians when there are any.

    Position t = (value - human median) / (AI median - human median): t >= 1 is at or past the
    typical AI value, t <= 0 at or past the typical human value.
    """
    out = []
    for key, (kind, sentence, fmt) in _STATS.items():
        v = stats.get(key)
        if v is None:
            continue
        text = sentence.format(v=fmt(v))
        if not medians:
            out.append({"kind": kind, "text": text, "weight": "weak", "_order": 9.0})
            continue
        h, a = medians["human"].get(key), medians["ai"].get(key)
        if not isinstance(h, (int, float)) or not isinstance(a, (int, float)) or a == h:
            continue
        t = (v - h) / (a - h)
        side = "AI" if t >= 0.5 else "human"
        dist = abs(t - 0.5)
        weight = "strong" if dist >= 0.5 else "moderate" if dist >= 0.25 else "weak"
        text += f" In our human samples the median is {fmt(h)}; in AI samples, {fmt(a)}."
        if weight != "weak":
            text += f" That is closer to typical {side} writing."
        out.append({"kind": kind, "text": text, "weight": weight, "_order": -dist})
    out.sort(key=lambda r: r["_order"])
    for r in out:
        r.pop("_order")
    return out
