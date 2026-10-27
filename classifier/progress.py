"""Chart every evaluated run against the GPTZero-level target (docs/roadmap.md), one point per run.

  classifier/.venv/bin/python classifier/progress.py     # -> classifier/reports/progress.png

Reads classifier/reports/<date>.json and <date>-<round>.json (the nightly writes these), and
prints the same numbers as a table. All numbers are classifier-only, texts of 50+ words, on
held-out sources, except college essays (out-of-distribution, all lengths). The live model
(calibration/classifier.json) is ringed.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from clf_common import CLF_DIR, REPORTS_DIR  # noqa: E402

NAME = re.compile(r"^\d{4}-\d\d-\d\d(-\d+)?$")
LIVE = CLF_DIR.parent / "calibration" / "classifier.json"


def rate(parts: list[dict]) -> float | None:
    n = sum(p["n"] for p in parts)
    return sum(p["flagged"] for p in parts) / n if n else None


def point(rep: dict) -> dict:
    rule, by = rep["gate"]["rules"]["classifier_only"], rep["by_rule"]["classifier_only"]
    claude = [by[k]["ai"]["*all*|claude"] for k in ("holdout|50-149", "holdout|150+")
              if "*all*|claude" in by.get(k, {}).get("ai", {})]
    college = by.get("ood", {}).get("human", {}).get("ood-college-essay")
    return {
        "chatgpt": rule["chatgpt_catch_holdout"]["rate"],
        "claude": rate(claude),
        "false_flags": rule["false_flags_overall"]["rate"],
        "non_native": rule["false_flags_non_native"]["rate"],
        "college": college["false_flag"] if college else None,
    }


def load() -> list[dict]:
    rows = []
    reports = [p for p in REPORTS_DIR.glob("*.json") if NAME.match(p.stem)]
    for p in sorted(reports, key=lambda p: (p.stem[:10], int(p.stem[11:] or 1))):
        rep = json.loads(p.read_text())
        rnd = p.stem[11:]  # "" for a night's first run, "2" for its second
        label = p.stem[5:10] + (f" #{rnd}" if rnd else "")
        rows.append({"label": label, "run": rep["run"].rsplit("-", 1)[-1][:8],
                     "rows": rep.get("trained", {}).get("train_rows"), **point(rep)})
    return rows


def live_run() -> str | None:
    try:
        return json.loads(LIVE.read_text()).get("run", "").rsplit("-", 1)[-1][:8] or None
    except (OSError, ValueError):
        return None


def table(rows: list[dict]) -> str:
    pct = lambda v: "   -" if v is None else f"{v * 100:5.1f}"  # noqa: E731
    out = ["run         ChatGPT  Claude  flagged  non-native  college   rows"]
    for r in rows:
        out.append(f"{r['label']:<11} {pct(r['chatgpt'])}   {pct(r['claude'])}   {pct(r['false_flags'])}"
                   f"     {pct(r['non_native'])}     {pct(r['college'])}  {r['rows'] or '-':>6}")
    return "\n".join(out)


def chart(rows: list[dict], out: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    x = list(range(len(rows)))
    live = live_run()
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(10, 7.5), sharex=True)
    fig.suptitle("Squint classifier, one point per nightly run", fontsize=13, x=0.06, ha="left")

    def series(ax, key, label, color):
        pts = [(i, r[key] * 100) for i, r in zip(x, rows) if r[key] is not None]
        ax.plot(*zip(*pts), marker="o", color=color, label=label, linewidth=1.8)
        for i, r in zip(x, rows):
            if r["run"] == live and r[key] is not None:
                ax.plot(i, r[key] * 100, "o", ms=13, mfc="none", mec="black", mew=1.5)

    series(top, "chatgpt", "ChatGPT", "#10a37f")
    series(top, "claude", "Claude", "#d97757")
    top.axhline(97, color="gray", ls="--", lw=1)
    top.text(x[0], 97.2, "target 97%", color="gray", fontsize=9)
    top.set_ylabel("AI text caught (%)")
    top.legend(loc="lower right", frameon=False)

    series(bottom, "false_flags", "All held-out humans", "#4a6fa5")
    series(bottom, "non_native", "Non-native writers", "#8e6bbf")
    series(bottom, "college", "College essays", "#c0504d")
    bottom.axhline(1, color="gray", ls="--", lw=1)
    bottom.text(x[0], 1.15, "target 1%", color="gray", fontsize=9)
    bottom.set_ylabel("Humans wrongly flagged (%)")
    bottom.set_ylim(bottom=0)
    bottom.legend(loc="upper left", frameon=False)
    bottom.set_xticks(x, [r["label"] for r in rows], rotation=0, fontsize=9)

    for ax in (top, bottom):
        ax.grid(axis="y", alpha=0.3)
        ax.spines[["top", "right"]].set_visible(False)
    fig.text(0.06, 0.005, "50+ words, held-out sources; college essays all lengths. Ringed: the live model.",
             fontsize=8.5, color="gray")
    fig.tight_layout(rect=(0, 0.02, 1, 0.97))
    fig.savefig(out, dpi=150)


def main() -> int:
    rows = load()
    if not rows:
        print("no reports yet")
        return 0
    out = REPORTS_DIR / "progress.png"
    chart(rows, out)
    print(table(rows))
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
