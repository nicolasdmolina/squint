import random

import pytest

from conftest import FALCON_TOKENIZER, QWEN_TOKENIZER
from squint.textproc import (
    TextTokenizer,
    count_words,
    display_tokens,
    paragraph_spans,
    sentence_spans,
    utf16_map,
    word_spans,
)

UNICODE_SAMPLES = [
    "Hello  world!\n\nNew   paragraph here.\tTabbed\t\tagain.",
    "I love pizza 🍕🍕 and 👍🏽 thumbs, family 👨‍👩‍👧 emoji, flags 🇨🇦🇫🇷.",
    "“Don’t,” she said — ‘really’… it’s fine. «Quoted» „low“.",
    "Café naïve résumé São Paulo Zürich Øresund façade.",
    "Café and crème brûlée, decomposed accents.",
    "Price: 100 €  thin space and　ideographic space.",
    "这是一个测试。日本語のテキストも。한국어 문장입니다.",
    "  \n leading and trailing whitespace \n\n  ",
    "Line one\n\n\n\nLine two\r\nLine three\rLine four",
    "𝔘𝔫𝔦𝔠𝔬𝔡𝔢 𝒽𝑒𝓁𝓁𝑜 and 𝟙𝟚𝟛 astral letters.",
    "zero​width‍joiner⁠word and soft­hyphen",
    "مرحبا بالعالم and עברית mixed with English.",
    "\ufeffBOM at the start, then text.",
    "x",
    "Ünïcödé — ellipsis… dashes – and ‘single’ quotes; tabs\tand  doubles   spaces",
    "é́́ stacked combining marks z̵̡̢",
]

_POOL = (
    list("abcdefghijklmnopqrstuvwxyzABCDEFG0123456789.,;:!?'\"()-")
    + [" ", " ", " ", "\n", "\n\n", "\t", " ", " ", "\r\n"]
    + list("éèñüßøåçÆœ“”‘’—–…«»€£¥")
    + ["́", "̈", "​", "‍", "️"]
    + list("中文日本語한국어")
    + ["🍕", "👍🏽", "👨‍👩‍👧", "🇨🇦", "😀", "𝔘", "𝟙", "🧑🏿‍🚀"]
)


def _fuzz_texts(n=150, seed=1234):
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        out.append("".join(rng.choice(_POOL) for _ in range(rng.randint(1, 60))))
    return out


TOKENIZERS = []
for _p in (QWEN_TOKENIZER, FALCON_TOKENIZER):
    TOKENIZERS.append(pytest.param(_p, id=_p.parent.name,
                                   marks=pytest.mark.skipif(not _p.exists(), reason=f"{_p} not present")))


@pytest.fixture(scope="module", params=TOKENIZERS)
def tokenizer(request):
    return TextTokenizer(str(request.param))


def assert_tiles(text, offsets, groups):
    n = len(offsets)
    if not groups:
        assert all(e <= s for s, e in offsets)
        return
    # no gaps or overlaps between consecutive display tokens, and none is empty
    for a, b in zip(groups, groups[1:]):
        assert a.end == b.start, (text, a, b)
    for g in groups:
        assert g.start < g.end, (text, g)
    # only whitespace may stay outside the tokens
    assert text[: groups[0].start].strip() == "", (text, groups[0])
    assert text[groups[-1].end:].strip() == "", (text, groups[-1])
    # every model token belongs to exactly one display token, in order
    assert groups[0].first == 0
    for a, b in zip(groups, groups[1:]):
        assert a.stop == b.first
    assert groups[-1].stop == n


def test_utf16_map_counts_astral_as_two():
    text = "a😀bé𝔘"
    m = utf16_map(text)
    assert m == [0, 1, 3, 4, 5, 7]
    assert m[-1] == len(text.encode("utf-16-le")) // 2


def test_words():
    text = "  one\ttwo\n\nthree  four five "
    assert count_words(text) == 5  # NBSP separates words like any other whitespace
    assert [text[s:e] for s, e in word_spans(text)] == ["one", "two", "three", "four", "five"]


@pytest.mark.parametrize("text", UNICODE_SAMPLES)
def test_display_tokens_tile_unicode(tokenizer, text):
    ids, offsets = tokenizer.encode(text)
    assert len(ids) == len(offsets)
    assert_tiles(text, offsets, display_tokens(text, offsets))


def test_display_tokens_tile_fuzz(tokenizer):
    for text in _fuzz_texts():
        ids, offsets = tokenizer.encode(text)
        assert_tiles(text, offsets, display_tokens(text, offsets))


def test_display_tokens_synthetic_cases():
    # overlapping pieces of one character merge; zero-width tokens join a neighbour; gaps close
    text = "ab😀 cd"
    offsets = [(0, 0), (0, 2), (2, 3), (2, 3), (3, 4), (5, 7), (7, 7)]
    groups = display_tokens(text, offsets)
    assert [(g.start, g.end, g.first, g.stop) for g in groups] == [(0, 2, 0, 2), (2, 3, 2, 4), (3, 5, 4, 5), (5, 7, 5, 7)]
    # a skipped non-space character goes to the previous token, skipped whitespace to the next
    text = "ab́  cd"
    groups = display_tokens(text, [(0, 2), (5, 7)])
    assert [(g.start, g.end) for g in groups] == [(0, 3), (3, 7)]
    # non-whitespace before the first or after the last token is pulled in
    text = "xab cdy"
    groups = display_tokens(text, [(1, 3), (3, 6)])
    assert groups[0].start == 0 and groups[-1].end == len(text)


def test_paragraphs_blank_lines_and_single_newlines():
    text = "First para line one.\nStill first.\n\n  \nSecond para.\n\n\nThird."
    paras = paragraph_spans(text)
    assert [text[s:e] for s, e in paras] == ["First para line one.\nStill first.", "Second para.", "Third."]
    text2 = "Line A\nLine B\n\rLine C"
    assert [text2[s:e] for s, e in paragraph_spans(text2)] == ["Line A", "Line B", "Line C"]


def test_sentences():
    text = ("Dr. Smith met J. K. Rowling at 5 p.m. today. It went well! Did it? "
            "“Stop.” She left… then came back, e.g. at noon. Fine...\nA heading\n\nNew paragraph here.")
    paras = paragraph_spans(text)
    sents = sentence_spans(text, paras)
    got = [text[s:e] for s, e, _ in sents]
    assert got == [
        "Dr. Smith met J. K. Rowling at 5 p.m. today.",
        "It went well!",
        "Did it?",
        "“Stop.”",
        "She left… then came back, e.g. at noon.",
        "Fine...",
        "A heading",
        "New paragraph here.",
    ]
    assert [p for _, _, p in sents] == [0, 0, 0, 0, 0, 0, 0, 1]


def test_tokenizer_matches_between_falcon_files():
    """The base and instruct Falcon tokenizers are byte-identical upstream; we ship one copy."""
    if not FALCON_TOKENIZER.exists():
        pytest.skip("falcon tokenizer not present")
    tok = TextTokenizer(str(FALCON_TOKENIZER))
    ids, _ = tok.encode("Binoculars scores text.")
    assert ids and all(isinstance(i, int) for i in ids)
    assert len(tok.vocab()) == 65024
