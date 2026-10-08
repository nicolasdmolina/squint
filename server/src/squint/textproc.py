"""Text plumbing: tokenizer, display tokens that tile the text, UTF-16 offsets, words,
paragraphs and sentences. Pure functions, no model needed."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

WORD_RE = re.compile(r"\S+")


def word_spans(text: str) -> list[tuple[int, int]]:
    """Words are maximal runs of non-whitespace characters (Python str indices)."""
    return [m.span() for m in WORD_RE.finditer(text)]


def count_words(text: str) -> int:
    return sum(1 for _ in WORD_RE.finditer(text))


def valid_unicode(text: str) -> bool:
    """False when the text holds lone surrogates (JSON allows "\\ud83d"; tokenizers reject it)."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def utf16_map(text: str) -> list[int]:
    """out[i] = number of UTF-16 code units in text[:i]; len(out) == len(text) + 1."""
    out = [0] * (len(text) + 1)
    acc = 0
    for i, ch in enumerate(text):
        out[i] = acc
        acc += 2 if ord(ch) > 0xFFFF else 1
    out[len(text)] = acc
    return out


# --------------------------------------------------------------------------------------------
# tokenizer


class TextTokenizer:
    """The Hugging Face fast tokenizer for the model pair (same ids as the reference code)."""

    def __init__(self, path: str):
        from tokenizers import Tokenizer

        self.path = path
        self._tok = Tokenizer.from_file(path)
        self._decode = lru_cache(maxsize=65536)(self._decode_one)

    def encode(self, text: str) -> tuple[list[int], list[tuple[int, int]]]:
        enc = self._tok.encode(text)  # default add_special_tokens=True, like the reference call
        return list(enc.ids), [tuple(o) for o in enc.offsets]

    def _decode_one(self, token_id: int) -> str:
        if token_id < 0:
            return ""
        try:
            return self._tok.decode([int(token_id)], skip_special_tokens=False)
        except Exception:
            return ""

    def decode_token(self, token_id: int) -> str:
        return self._decode(int(token_id))

    def vocab(self) -> dict[str, int]:
        return self._tok.get_vocab(with_added_tokens=True)


# --------------------------------------------------------------------------------------------
# display tokens


@dataclass
class DisplayToken:
    start: int  # Python str index, inclusive
    end: int  # exclusive
    first: int  # first model token index in this group
    stop: int  # one past the last model token index


def display_tokens(text: str, offsets: list[tuple[int, int]]) -> list[DisplayToken]:
    """Group model tokens into display tokens whose character ranges tile `text`.

    Byte-level BPE can split one character across several tokens (emoji, CJK, combining
    marks); those tokens report overlapping ranges and are merged into one display token.
    Characters a normaliser skipped are attached to a neighbour: leading non-whitespace of a
    gap goes to the previous token, the rest (whitespace) to the next one. Leading and trailing
    whitespace of the whole text may stay outside every token.
    """
    groups: list[DisplayToken] = []
    pending_zero: list[int] = []  # zero-width tokens before the first real group
    for idx, (s, e) in enumerate(offsets):
        if e <= s:
            if groups:
                groups[-1].stop = idx + 1
            else:
                pending_zero.append(idx)
            continue
        if groups and s < groups[-1].end:
            g = groups[-1]
            g.end = max(g.end, e)
            g.stop = idx + 1
            continue
        first = pending_zero[0] if (pending_zero and not groups) else idx
        groups.append(DisplayToken(start=s, end=e, first=first, stop=idx + 1))
        pending_zero = []
    if not groups:
        return []

    # close gaps between consecutive groups
    for prev, cur in zip(groups, groups[1:]):
        if cur.start > prev.end:
            gap = text[prev.end:cur.start]
            k = 0
            while k < len(gap) and not gap[k].isspace():
                k += 1
            prev.end += k
            cur.start = prev.end
    # text edges: keep only whitespace outside the tokens
    if text[: groups[0].start].strip():
        groups[0].start = 0
    if text[groups[-1].end:].strip():
        groups[-1].end = len(text)
    return groups


def core_index(text: str, start: int, end: int) -> int:
    """Index of the first non-whitespace character in [start, end), or start."""
    for i in range(start, end):
        if not text[i].isspace():
            return i
    return start


# --------------------------------------------------------------------------------------------
# paragraphs and sentences

_BLANK_LINE = re.compile(r"\n[^\S\n]*\n")
_PARA_SEP_BLANK = re.compile(r"\n(?:[^\S\n]*\n)+")
_PARA_SEP_LINE = re.compile(r"\n+")

_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "e.g", "i.e", "eg", "ie",
    "fig", "no", "inc", "ltd", "co", "corp", "u.s", "u.k", "a.m", "p.m", "approx", "dept",
    "est", "gen", "gov", "mt", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept",
    "oct", "nov", "dec", "vol", "ch", "pp", "p", "al", "cf", "ca",
}
_SENT_END = re.compile(r"(?:[.!?…]+|\.\.\.)[\"'”’»)\]]*(?=\s|$)")


def _trim(text: str, s: int, e: int) -> tuple[int, int] | None:
    while s < e and text[s].isspace():
        s += 1
    while e > s and text[e - 1].isspace():
        e -= 1
    return (s, e) if e > s else None


def paragraph_spans(text: str) -> list[tuple[int, int]]:
    """Paragraphs are separated by blank lines; if the text has none, by single newlines."""
    sep = _PARA_SEP_BLANK if _BLANK_LINE.search(text) else _PARA_SEP_LINE
    spans, pos = [], 0
    for m in sep.finditer(text):
        t = _trim(text, pos, m.start())
        if t:
            spans.append(t)
        pos = m.end()
    t = _trim(text, pos, len(text))
    if t:
        spans.append(t)
    return spans


def _is_abbreviation(text: str, para_start: int, punct_start: int, punct: str) -> bool:
    if not punct.startswith(".") or punct.startswith(".."):
        return False
    j = punct_start
    while j > para_start and not text[j - 1].isspace():
        j -= 1
    word = text[j:punct_start].lstrip("\"'(“‘[").lower()
    if not word:
        return False
    if word in _ABBREVIATIONS:
        return True
    if len(word) == 1 and word.isalpha():  # initials: "J. K. Rowling"
        return True
    return False


def sentence_spans(text: str, paragraphs: list[tuple[int, int]]) -> list[tuple[int, int, int]]:
    """(start, end, paragraph_index) for each sentence, trimmed of surrounding whitespace."""
    out: list[tuple[int, int, int]] = []
    for p_idx, (ps, pe) in enumerate(paragraphs):
        cuts = []
        for m in _SENT_END.finditer(text, ps, pe):
            punct = m.group(0)
            if _is_abbreviation(text, ps, m.start(), punct):
                continue
            nxt = m.end()
            while nxt < pe and text[nxt].isspace() and text[nxt] != "\n":
                nxt += 1
            if nxt < pe and text[nxt].islower():
                continue  # "e.g. this" / mid-sentence ellipsis
            cuts.append(m.end())
        # single line breaks inside a paragraph also end a sentence (lists, headings)
        for m in re.finditer(r"\n", text[ps:pe]):
            cuts.append(ps + m.start())
        cuts = sorted(set(c for c in cuts if ps < c < pe))
        pos = ps
        for c in cuts + [pe]:
            t = _trim(text, pos, c)
            if t:
                out.append((t[0], t[1], p_idx))
            pos = c
    return out
