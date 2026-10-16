import json

import pytest

from conftest import PAIR, QWEN_TOKENIZER, FakeBackend, FakeTokenizer, thresholds, words
from squint.analysis import Analysis, TextTooShortToScore, score_text, segment_windows
from squint.calibration import Calibration, CalibrationStore, length_bucket
from squint.config import Limits
from squint.textproc import TextTokenizer


def analyse(text, surprise=1.8, cal=None, tok=None):
    tok = tok or FakeTokenizer()
    backend = FakeBackend(surprise)
    backend.load()
    scored = score_text(text, tok, backend)
    return Analysis(scored, cal or Calibration(None, None), Limits(), tok)


def cal(**over):
    return Calibration(thresholds(**over), None)


def test_length_buckets():
    assert [length_bucket(n) for n in (0, 19, 20, 49, 50, 149, 150, 2500)] == [
        "20-49", "20-49", "20-49", "20-49", "50-149", "50-149", "150+", "150+"]


@pytest.mark.parametrize("n_words,surprise,band", [
    (30, 1.2, "likely_ai"),      # 0.60 < 0.70
    (30, 1.7, "uncertain"),      # 0.85 within [0.70, 1.00]
    (30, 2.2, "likely_human"),   # 1.10 > 1.00
    (100, 1.5, "likely_ai"),     # 0.75 < 0.80
    (100, 1.75, "uncertain"),    # 0.875
    (100, 2.0, "likely_human"),  # 1.00 > 0.97
    (200, 1.75, "uncertain"),    # 0.875 within [0.85, 0.95]
    (200, 1.5, "likely_ai"),
    (200, 2.0, "likely_human"),
])
def test_banding_by_bucket(n_words, surprise, band):
    a = analyse(words(n_words), surprise, cal())
    assert a.score == pytest.approx(surprise / 2.0)
    v = a.verdict()
    assert v["band"] == band
    assert v["length_bucket"] == length_bucket(n_words)
    assert v["thresholds"] == thresholds()["buckets"][length_bucket(n_words)]
    assert v["confidence"] == ("low" if n_words < 150 else "normal")
    assert v["label"] and v["explanation"]


def test_band_boundaries_are_uncertain():
    t = thresholds()
    t["buckets"]["150+"] = {"ai_below": 0.875, "human_above": 0.875}
    a = analyse(words(200), 1.75, Calibration(t, None))
    assert a.score == 0.875
    assert a.verdict()["band"] == "uncertain"


@pytest.mark.parametrize("calibration", [
    Calibration(None, None),
    Calibration(thresholds(pair={"observer": "Falcon-7B (4-bit)", "performer": "Falcon-7B-Instruct (4-bit)"}), None),
    Calibration({**thresholds(), "buckets": {"20-49": {"ai_below": 0.7, "human_above": 1.0}}}, None),
    Calibration({**thresholds(), "buckets": {**thresholds()["buckets"], "150+": {"ai_below": None, "human_above": 1}}}, None),
])
def test_uncalibrated_path(calibration):
    a = analyse(words(300), 1.0, calibration)
    r = a.result()
    v = r["verdict"]
    assert v["band"] == "uncalibrated"
    assert v["label"] == "Not tuned yet"
    assert v["thresholds"] is None
    assert v["ai_percent"] is None
    assert v["score"] == pytest.approx(0.5)
    assert v["confidence"] == "normal"
    # segments are still reported (for the heat map) but never flagged
    assert r["segments"] and not any(s["flagged"] for s in r["segments"])
    # reasons fall back to descriptive text
    assert r["reasons"] and all(x["weight"] == "weak" for x in r["reasons"])


def test_calibration_store_reads_and_rereads(tmp_path):
    store = CalibrationStore(tmp_path)
    assert store.current().thresholds is None and store.current().report is None
    (tmp_path / "thresholds.json").write_text(json.dumps(thresholds()))
    assert store.current().ready_for(PAIR)
    assert store.current().version == "2026-10-07"
    (tmp_path / "thresholds.json").write_text("{not json")
    assert store.current().thresholds is None  # malformed behaves as absent
    (tmp_path / "report.json").write_text(json.dumps({"version": "x"}))
    assert store.current().report == {"version": "x"}


def test_short_texts_have_no_percent():
    a = analyse(words(149), 1.0, cal())
    v = a.verdict()
    assert v["ai_percent"] is None and a.segments == []
    assert v["confidence"] == "low"
    assert v["band"] == "likely_ai"


def test_segments_and_ai_percent():
    assert segment_windows(149, 150, 75) == []
    assert segment_windows(150, 150, 75) == [(0, 150)]
    assert segment_windows(200, 150, 75) == [(0, 150), (50, 200)]
    assert segment_windows(300, 150, 75) == [(0, 150), (75, 225), (150, 300)]
    # first 150 tokens (= words for the fake tokenizer) AI-like, the rest human-like
    text = words(300)
    a = analyse(text, lambda i: 1.0 if i < 150 else 3.0, cal())
    segs = a.segments
    assert [(s["word_start"], s["word_end"]) for s in segs] == [(0, 150), (75, 225), (150, 300)]
    assert [s["flagged"] for s in segs] == [True, False, False]
    assert segs[0]["score"] == pytest.approx(0.5)
    assert segs[1]["score"] == pytest.approx(1.0)
    assert a.ai_percent == 50
    # segment offsets point at the first/last word of the window
    assert text[segs[1]["start"]:segs[1]["end"]] == " ".join(f"word{i}" for i in range(75, 225))


def test_token_fields_and_signal():
    a = analyse(words(40), lambda i: 0.5 if i < 20 else 4.0)
    toks = a.tokens
    assert len(toks) == 40
    t0 = toks[0]
    assert t0["surprise"] is None and t0["expected_surprise"] is None and t0["rank"] is None
    assert t0["signal"] == 0 and t0["top"] == []
    for t in toks:
        assert -1 <= t["signal"] <= 1 and -1 <= t["signal_smooth"] <= 1
    assert all(t["signal"] > 0 for t in toks[1:20])  # more predictable than expected: AI-like
    assert all(t["signal"] < 0 for t in toks[20:])  # more surprising: human-like
    assert toks[5]["signal_smooth"] > 0 and toks[35]["signal_smooth"] < 0
    t5 = toks[5]
    assert set(t5) == {"i", "start", "end", "text", "surprise", "expected_surprise", "signal",
                       "signal_smooth", "rank", "top", "sentence"}
    assert len(t5["top"]) == 5 and all(set(x) == {"text", "p"} for x in t5["top"])
    assert t5["surprise"] == 0.5 and t5["expected_surprise"] == 2.0


def test_stats_are_consistent_with_score():
    text = "This is a sentence that goes on and on for a while. " * 12
    a = analyse(text, lambda i: 1.0 + (i % 3))
    st = a.stats
    assert set(st) == {"top1_rate", "top5_rate", "mean_surprise", "mean_expected_surprise", "sentence_score_spread"}
    assert st["mean_surprise"] / st["mean_expected_surprise"] == pytest.approx(a.score, rel=1e-3)
    assert 0 <= st["top1_rate"] <= st["top5_rate"] <= 1
    assert st["sentence_score_spread"] is not None


def test_sentences_paragraphs_cover_tokens():
    text = ("The first sentence is right here and it is fine. The second one follows it closely now.\n\n"
            "A new paragraph starts with this sentence today. And then it ends with another one here.")
    a = analyse(text, 1.6, cal())
    r = a.result()
    sents, paras, toks = r["sentences"], r["paragraphs"], r["tokens"]
    assert len(sents) == 4 and len(paras) == 2
    assert [s["paragraph"] for s in sents] == [0, 0, 1, 1]
    assert sents[0]["token_start"] == 0 and sents[-1]["token_end"] == len(toks)
    for a_, b_ in zip(sents, sents[1:]):
        assert a_["token_end"] == b_["token_start"]
    for s in sents:
        assert all(toks[k]["sentence"] == s["i"] for k in range(s["token_start"], s["token_end"]))
        assert s["lean"] in {"ai", "neutral", "human"}
    assert text[sents[2]["start"]:sents[2]["end"]] == "A new paragraph starts with this sentence today."
    assert text[paras[1]["start"]:paras[1]["end"]].startswith("A new paragraph")


def test_reasons_against_medians():
    a = analyse(words(200), 1.0, cal())
    rs = a.result()["reasons"]
    assert {r["kind"] for r in rs} >= {"predictability", "top_five", "surprise"}
    order = {"strong": 0, "moderate": 1, "weak": 2}
    assert [order[r["weight"]] for r in rs] == sorted(order[r["weight"]] for r in rs)
    assert all(isinstance(r["text"], str) and r["text"] for r in rs)


def test_result_shape():
    r = analyse(words(160), 1.8, cal()).result()
    assert set(r) == {"word_count", "token_count", "model_pair", "verdict", "reasons", "stats", "tokens",
                      "sentences", "paragraphs", "segments"}
    assert set(r["verdict"]) == {"band", "label", "confidence", "length_bucket", "detector", "score", "thresholds",
                                 "classifier", "ai_percent", "explanation"}
    assert r["verdict"]["detector"] == "binoculars" and r["verdict"]["classifier"] is None
    assert r["model_pair"] == PAIR
    json.dumps(r, allow_nan=False)


def test_batch_row_shape():
    a = analyse(words(160), 1.8, cal())
    row = a.batch_row("abc")
    assert set(row) == {"id", "word_count", "token_count", "score", "stats", "segments", "model_pair"}
    assert row["id"] == "abc" and row["word_count"] == 160
    assert row["segments"] and all(set(s) == {"word_start", "word_end", "start", "end", "score"} for s in row["segments"])
    json.dumps(row, allow_nan=False)


def test_too_short_to_score():
    backend = FakeBackend()
    backend.load()
    with pytest.raises(TextTooShortToScore):
        score_text("one", FakeTokenizer(), backend)


@pytest.mark.skipif(not QWEN_TOKENIZER.exists(), reason="stand-in tokenizer not present")
def test_utf16_offsets_with_real_tokenizer():
    tok = TextTokenizer(str(QWEN_TOKENIZER))
    text = ("“Smart” quotes, café, naïve, café — emoji 🍕👍🏽👨‍👩‍👧 and 𝔘𝔫𝔦 in a sentence.  Two  spaces.\n\n"
            "这是中文。 Second paragraph… with\ttabs and NBSP.\n\n\nThird paragraph after many newlines 🇨🇦!  ")
    a = analyse(text, 1.8, cal(), tok=tok)
    r = a.result()
    u16 = text.encode("utf-16-le")

    def js_slice(s, e):
        return u16[2 * s:2 * e].decode("utf-16-le")

    toks = r["tokens"]
    for t in toks:
        assert js_slice(t["start"], t["end"]) == t["text"]
    for x, y in zip(toks, toks[1:]):
        assert x["end"] == y["start"]
    assert js_slice(0, toks[0]["start"]).strip() == ""
    assert js_slice(toks[-1]["end"], len(u16) // 2).strip() == ""
    assert "".join(t["text"] for t in toks) == text.strip() or text.find("".join(t["text"] for t in toks)) >= 0
    for s in r["sentences"] + r["paragraphs"]:
        assert js_slice(s["start"], s["end"]).strip() == js_slice(s["start"], s["end"])
    assert js_slice(r["paragraphs"][2]["start"], r["paragraphs"][2]["end"]) == "Third paragraph after many newlines 🇨🇦!"


def test_token_zero_has_no_smoothed_signal_and_does_not_dilute_its_neighbours():
    toks = analyse(words(40), 0.5).tokens  # every scored token strongly AI-like
    assert toks[0]["signal"] == 0 and toks[0]["signal_smooth"] == 0
    assert toks[1]["signal_smooth"] > 0.5
    # token 1's window includes token 0, token 20's does not: same value means token 0 added nothing
    assert toks[1]["signal_smooth"] == pytest.approx(toks[20]["signal_smooth"])
    assert toks[3]["signal_smooth"] == pytest.approx(toks[20]["signal_smooth"])


def test_calibration_report_is_tied_to_the_model_pair():
    report = {"version": "x", "model_pair": dict(PAIR)}
    assert Calibration(None, report).report_for(PAIR) == report
    assert Calibration(None, {**report, "model_pair": {"observer": "A", "performer": "B"}}).report_for(PAIR) is None
    assert Calibration(None, {"version": "x"}).report_for(PAIR) is None
    assert Calibration(None, {"version": "x", "model_pair": "nope"}).report_for(PAIR) is None
    assert Calibration(None, None).report_for(PAIR) is None
