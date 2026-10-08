"""calibration/thresholds.json and calibration/report.json (docs/calibration-format.md)."""

from __future__ import annotations

import json
import logging
import math
import os
import threading
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("squint.calibration")

BUCKETS = ("20-49", "50-149", "150+")
DEFAULT_WINDOW_WORDS = 150
DEFAULT_STRIDE_WORDS = 75
# Paper thresholds (Falcon-7B pair at bfloat16). Never used for verdicts: only to centre the
# heat-map signal and the sentence/paragraph lean hints while the pair is uncalibrated.
REFERENCE_THRESHOLDS = {"ai_below": 0.8536432310785527, "human_above": 0.9015310749276843}


def length_bucket(words: int) -> str:
    if words < 50:
        return "20-49"
    if words < 150:
        return "50-149"
    return "150+"


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


@dataclass(frozen=True)
class Calibration:
    thresholds: dict | None
    report: dict | None

    @property
    def version(self) -> str | None:
        if self.thresholds and isinstance(self.thresholds.get("version"), str):
            return self.thresholds["version"]
        return None

    def ready_for(self, model_pair: dict) -> bool:
        t = self.thresholds
        if not t:
            return False
        mp = t.get("model_pair") or {}
        if mp.get("observer") != model_pair.get("observer") or mp.get("performer") != model_pair.get("performer"):
            return False
        return all(self._bucket_ok(t, b) for b in BUCKETS)

    def report_for(self, model_pair: dict) -> dict | None:
        """report.json, only when it was computed for this model pair (like thresholds.json)."""
        r = self.report
        if not r:
            return None
        mp = r.get("model_pair") if isinstance(r.get("model_pair"), dict) else {}
        if mp.get("observer") != model_pair.get("observer") or mp.get("performer") != model_pair.get("performer"):
            return None
        return r

    @staticmethod
    def _bucket_ok(t: dict, bucket: str) -> bool:
        b = (t.get("buckets") or {}).get(bucket)
        return isinstance(b, dict) and _num(b.get("ai_below")) and _num(b.get("human_above"))

    def bucket(self, bucket: str, model_pair: dict) -> dict | None:
        if not self.ready_for(model_pair):
            return None
        b = self.thresholds["buckets"][bucket]
        return {"ai_below": float(b["ai_below"]), "human_above": float(b["human_above"])}

    def lean_thresholds(self, words: int, model_pair: dict) -> dict:
        return self.bucket(length_bucket(max(words, 20)), model_pair) or dict(REFERENCE_THRESHOLDS)

    def segment_params(self) -> tuple[int, int]:
        seg = (self.thresholds or {}).get("segment") or {}
        w, s = seg.get("window_words"), seg.get("stride_words")
        window = int(w) if _num(w) and w > 0 else DEFAULT_WINDOW_WORDS
        stride = int(s) if _num(s) and s > 0 else DEFAULT_STRIDE_WORDS
        return window, stride

    def flag_below(self, model_pair: dict) -> float | None:
        if not self.ready_for(model_pair):
            return None
        v = ((self.thresholds or {}).get("segment") or {}).get("flag_below")
        return float(v) if _num(v) else None

    def medians(self, model_pair: dict) -> dict | None:
        if not self.ready_for(model_pair):
            return None
        m = (self.thresholds or {}).get("medians") or {}
        if isinstance(m.get("human"), dict) and isinstance(m.get("ai"), dict):
            return m
        return None


class CalibrationStore:
    """Reads the calibration files, re-reading them when they change on disk."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[tuple, dict | None]] = {}

    def _read(self, name: str) -> dict | None:
        path = self.directory / name
        try:
            st = os.stat(path)
            key = (st.st_mtime_ns, st.st_size)
        except FileNotFoundError:
            key = None
        with self._lock:
            cached = self._cache.get(name)
            if cached and cached[0] == key:
                return cached[1]
            data = None
            if key is not None:
                try:
                    with open(path, encoding="utf-8") as fh:
                        data = json.load(fh)
                    if not isinstance(data, dict):
                        raise ValueError("top level is not an object")
                except Exception as exc:  # malformed file -> behave as if absent
                    log.warning("ignoring %s: %s", path, exc)
                    data = None
            self._cache[name] = (key, data)
            return data

    def current(self) -> Calibration:
        return Calibration(thresholds=self._read("thresholds.json"), report=self._read("report.json"))
