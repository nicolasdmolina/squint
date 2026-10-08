"""Shared helpers for the Squint calibration scripts (stdlib only).

Length buckets, word counting, sentence splitting, deterministic hashing and JSONL IO.
The bucket edges must match the server: 20-49, 50-149, 150+ words.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Iterable, Iterator

CAL_DIR = Path(__file__).resolve().parent
DATA_DIR = CAL_DIR / "data"
GEN_DIR = CAL_DIR / "generated"

BUCKETS = ("20-49", "50-149", "150+")
MIN_WORDS = 20
SEED = "squint-2026-10-07"


def word_count(text: str) -> int:
    return len(text.split())


def bucket_for(words: int) -> str | None:
    if words < MIN_WORDS:
        return None
    if words < 50:
        return "20-49"
    if words < 150:
        return "50-149"
    return "150+"


def stable_hash(*parts: object, seed: str = SEED) -> int:
    h = hashlib.sha256((seed + "|" + "|".join(str(p) for p in parts)).encode("utf-8"))
    return int.from_bytes(h.digest()[:8], "big")


def read_jsonl(path: str | Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: str | Path, rows: Iterable[dict]) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    tmp.replace(path)
    return n


def write_json(path: str | Path, obj: object) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


# --- text cleanup -----------------------------------------------------------------------

_MOJIBAKE = re.compile("[ÂÃâ][\u0080-¿‘-›Œ-Ÿˆ˜€™]")


def fix_mojibake(text: str) -> str:
    """Undo the common UTF-8-read-as-cp1252 corruption when it is clearly present."""
    if not _MOJIBAKE.search(text):
        return text
    try:
        fixed = text.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    return fixed


def normalize_text(text: str) -> str:
    text = fix_mojibake(text)
    # stray C1 control characters are cp1252 punctuation that was never decoded
    text = re.sub("[\u0080-\u009f]", lambda m: bytes([ord(m.group(0))]).decode("cp1252", "replace"), text)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    # trailing spaces on lines and runs of 3+ newlines are layout noise, not writing
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# --- sentence splitting -----------------------------------------------------------------

_ABBREV = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "e.g", "i.e", "inc", "ltd",
    "co", "corp", "u.s", "u.k", "no", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep",
    "sept", "oct", "nov", "dec", "gov", "gen", "sen", "rep", "mt", "ft", "approx",
}
# candidate boundary: terminal punctuation, optional closing quotes/brackets, whitespace
_BOUNDARY = re.compile(r"[.!?]+[\"'”’)\]]*(?=\s)")


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """Return (start, end) character spans of sentences. Paragraph breaks always end a
    sentence. Heuristic, dependency-free; good enough for choosing truncation points."""
    spans: list[tuple[int, int]] = []
    for pm in re.finditer(r"[^\n]+(?:\n(?!\s*\n)[^\n]+)*", text):
        p_start, p_end = pm.start(), pm.end()
        para = text[p_start:p_end]
        cur = 0
        for bm in _BOUNDARY.finditer(para):
            end = bm.end()
            # skip abbreviations and initials ("U.S.", "J. Smith")
            word = re.findall(r"[A-Za-z.]+$", para[cur:bm.start() + 1])
            token = word[0].rstrip(".").lower() if word else ""
            if bm.group(0).startswith(".") and (token in _ABBREV or (len(token) == 1 and token.isalpha())):
                continue
            nxt = para[end:].lstrip()
            if nxt and nxt[0].islower():
                continue
            seg = para[cur:end]
            if seg.strip():
                s = cur + (len(seg) - len(seg.lstrip()))
                spans.append((p_start + s, p_start + end))
            cur = end
        seg = para[cur:]
        if seg.strip():
            s = cur + (len(seg) - len(seg.lstrip()))
            e = cur + len(seg.rstrip())
            spans.append((p_start + s, p_start + e))
    return spans


def paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def iter_chunks(seq: list, n: int) -> Iterator[list]:
    for i in range(0, len(seq), n):
        yield seq[i:i + n]
