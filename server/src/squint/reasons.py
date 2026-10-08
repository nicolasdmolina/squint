"""Plain-English verdict explanations and reasons. Templates over numbers; no LLM."""

from __future__ import annotations

LABELS = {
    "likely_human": "Likely human",
    "uncertain": "Uncertain",
    "likely_ai": "Likely AI",
    "uncalibrated": "Not tuned yet",
}


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
