// Development-only result generator for the mock API. Produces deterministic, contract-shaped
// results (docs/api-contract.md) with plausible per-token numbers. Never imported by src/.

import type {
  Accuracy, Band, Lean, LengthBucket, Paragraph, Reason, Result, Segment, Sentence, Token, TopGuess,
} from '../src/types.ts';
import { aiCueWords, fixtures, fixtureText, type Style } from './fixtures.ts';

export const MODEL_PAIR = { observer: 'Falcon-7B (4-bit)', performer: 'Falcon-7B-Instruct (4-bit)' };

export const LIMITS = { min_words: 20, percent_min_words: 150, max_words: 2500, checks_per_hour: 30 };

const THRESHOLDS: Record<LengthBucket, { ai_below: number; human_above: number }> = {
  '20-49': { ai_below: 0.7, human_above: 1.0 },
  '50-149': { ai_below: 0.8, human_above: 0.97 },
  '150+': { ai_below: 0.8536, human_above: 0.95 },
};
const REFERENCE = { ai_below: 0.8536, human_above: 0.9015 };
const SEGMENT = { window: 150, stride: 75, flag_below: 0.85 };
const MEDIANS = {
  human: { top1_rate: 0.38, top5_rate: 0.66, mean_surprise: 2.9, sentence_score_spread: 0.11 },
  ai: { top1_rate: 0.66, top5_rate: 0.88, mean_surprise: 1.8, sentence_score_spread: 0.05 },
};

// ------------------------------------------------------------------------------------------
// seeded randomness

function hashString(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function makeRng(seed: number) {
  let a = seed >>> 0;
  const next = () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  return {
    next,
    range: (lo: number, hi: number) => lo + (hi - lo) * next(),
    int: (lo: number, hi: number) => Math.floor(lo + (hi - lo + 1) * next()),
    pick: <T,>(arr: readonly T[]) => arr[Math.floor(next() * arr.length)],
  };
}
type Rng = ReturnType<typeof makeRng>;

// ------------------------------------------------------------------------------------------
// text structure (mirrors server/src/squint/textproc.py closely enough for the UI)

export const countWords = (text: string) => (text.match(/\S+/g) ?? []).length;

const wordSpans = (text: string) => [...text.matchAll(/\S+/g)].map(m => [m.index!, m.index! + m[0].length] as const);

function trimSpan(text: string, s: number, e: number): [number, number] | null {
  while (s < e && /\s/.test(text[s])) s++;
  while (e > s && /\s/.test(text[e - 1])) e--;
  return e > s ? [s, e] : null;
}

function paragraphSpans(text: string): [number, number][] {
  const sep = /\n[^\S\n]*\n/.test(text) ? /\n(?:[^\S\n]*\n)+/g : /\n+/g;
  const out: [number, number][] = [];
  let pos = 0;
  for (const m of text.matchAll(sep)) {
    const t = trimSpan(text, pos, m.index!);
    if (t) out.push(t);
    pos = m.index! + m[0].length;
  }
  const t = trimSpan(text, pos, text.length);
  if (t) out.push(t);
  return out;
}

const ABBREVIATIONS = new Set(['mr', 'mrs', 'ms', 'dr', 'prof', 'sr', 'jr', 'st', 'vs', 'etc', 'e.g', 'i.e', 'inc', 'ltd', 'no']);

function sentenceSpans(text: string, paragraphs: [number, number][]): [number, number, number][] {
  const out: [number, number, number][] = [];
  paragraphs.forEach(([ps, pe], p) => {
    const cuts: number[] = [];
    const re = /[.!?]+["'”’)\]]*(?=\s|$)/g;
    re.lastIndex = ps;
    let m: RegExpExecArray | null;
    while ((m = re.exec(text)) && m.index < pe) {
      let j = m.index;
      while (j > ps && !/\s/.test(text[j - 1])) j--;
      const word = text.slice(j, m.index).replace(/^["'(“‘[]+/, '').toLowerCase();
      if (m[0].startsWith('.') && (ABBREVIATIONS.has(word) || /^[a-z]$/.test(word))) continue;
      cuts.push(m.index + m[0].length);
    }
    let pos = ps;
    for (const c of [...cuts.filter(c => c > ps && c < pe), pe]) {
      const t = trimSpan(text, pos, c);
      if (t) out.push([t[0], t[1], p]);
      pos = c;
    }
  });
  return out;
}

// ------------------------------------------------------------------------------------------
// a BPE-flavoured tokenizer: leading spaces ride on the next piece, long words split in two,
// contractions and punctuation stand alone, newline runs are their own tokens.

type PieceKind = 'word' | 'cont' | 'punct' | 'num' | 'nl';
type Piece = { start: number; end: number; kind: PieceKind };

const SUFFIXES = ['ically', 'ation', 'ative', 'ities', 'ment', 'ness', 'ible', 'able', 'ence', 'ance', 'ally', 'ings', 'ized', 'ity', 'ing', 'ous', 'ful', 'ize', 'ers'];
const isLetter = (c: string) => /[A-Za-zÀ-ɏ]/.test(c);
const isDigit = (c: string) => /\d/.test(c);

function splitWord(word: string): number[] {
  if (word.length < 9) return [word.length];
  const lower = word.toLowerCase();
  for (const suf of SUFFIXES) {
    if (lower.endsWith(suf) && word.length - suf.length >= 4) return [word.length - suf.length, suf.length];
  }
  if (word.length >= 11) {
    const half = Math.ceil(word.length / 2);
    return [half, word.length - half];
  }
  return [word.length];
}

function tokenize(text: string): Piece[] {
  const out: Piece[] = [];
  let i = 0;
  let end = text.length;
  while (i < end && /\s/.test(text[i])) i++;
  while (end > i && /\s/.test(text[end - 1])) end--;
  while (i < end) {
    let j = i;
    while (j < end && /\s/.test(text[j])) j++;
    if (text.slice(i, j).includes('\n')) {
      out.push({ start: i, end: j, kind: 'nl' });
      i = j;
      continue;
    }
    const c = text[j];
    let k = j + 1;
    if (isLetter(c)) {
      while (k < end && isLetter(text[k])) k++;
      const lengths = splitWord(text.slice(j, k));
      let at = j;
      lengths.forEach((len, n) => {
        out.push({ start: n === 0 ? i : at, end: at + len, kind: n === 0 ? 'word' : 'cont' });
        at += len;
      });
      i = k;
      continue;
    }
    if (isDigit(c)) {
      while (k < end && isDigit(text[k])) k++;
      out.push({ start: i, end: k, kind: 'num' });
      i = k;
      continue;
    }
    if ((c === "'" || c === '’') && i === j) {
      const m = /^(s|t|re|ll|m|d|ve)(?![A-Za-z])/.exec(text.slice(j + 1, j + 4));
      if (m) {
        out.push({ start: j, end: j + 1 + m[1].length, kind: 'cont' });
        i = j + 1 + m[1].length;
        continue;
      }
    }
    out.push({ start: i, end: k, kind: 'punct' });
    i = k;
  }
  return out;
}

// ------------------------------------------------------------------------------------------
// top-five guesses

const FUNCTION_WORDS = ['the', 'a', 'and', 'to', 'of', 'in', 'that', 'it', 'is', 'for', 'was', 'with', 'as', 'but', 'this', 'on', 'not', 'be', 'they', 'their', 'more', 'also', 'can', 'all'];
const PUNCT_ALTS = [',', '.', ' and', ';', ':', ' the', ' to', ' that', ' -', ' (', ' in'];
const SUFFIX_ALTS = ['ing', 'ed', 's', 'ly', 'ment', 'ation', 'al', 'er', 'ness', 'ive', 'able'];
const NEWLINE_ALTS = ['\n', ' The', ' In', ' I', ' This', ' It', ' But'];
const SYNONYMS: Record<string, string[]> = {
  vital: ['crucial', 'key', 'central', 'significant'], crucial: ['vital', 'key', 'critical', 'central'],
  important: ['essential', 'crucial', 'vital', 'key'], essential: ['vital', 'important', 'key', 'critical'],
  role: ['part', 'place', 'function', 'position'], rapidly: ['quickly', 'constantly', 'ever', 'fast'],
  digital: ['modern', 'online', 'technological', 'information'], landscape: ['world', 'age', 'era', 'environment'],
  community: ['connection', 'belonging', 'engagement', 'learning'], access: ['opportunity', 'availability', 'entry'],
  libraries: ['they', 'these', 'institutions', 'communities'], resources: ['services', 'tools', 'programs', 'opportunities'],
  furthermore: ['moreover', 'additionally', 'also', 'finally'], additionally: ['furthermore', 'moreover', 'also', 'finally'],
  conclusion: ['summary', 'short', 'the', 'closing'], society: ['future', 'world', 'community', 'public'],
  ensure: ['help', 'guarantee', 'allow', 'make'], benefits: ['advantages', 'reasons', 'appeals', 'strengths'],
  results: ['outcomes', 'success', 'loaves', 'bread'], process: ['time', 'rise', 'method', 'approach'],
  grandfather: ['dad', 'father', 'uncle', 'family'], store: ['shop', 'business', 'place', 'stand'],
  smell: ['sound', 'noise', 'feel', 'quiet'], boring: ['easy', 'simple', 'fine', 'quiet'],
  weird: ['strange', 'interesting', 'different', 'fun'], wizard: ['genius', 'god', 'saint', 'magician'],
  bread: ['sourdough', 'loaves', 'pizza', 'cookies'], starter: ['dough', 'yeast', 'sourdough', 'culture'],
  flavor: ['taste', 'aroma', 'texture', 'character'], texture: ['flavor', 'crumb', 'taste', 'crust'],
  timeline: ['schedule', 'status', 'deadline', 'plan'], deliver: ['complete', 'finish', 'send', 'provide'],
  reviewed: ['read', 'checked', 'looked', 'gone'], details: ['plan', 'timeline', 'requirements', 'notes'],
};

const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

function topFive(rng: Rng, piece: Piece, text: string, rank: number, probs: number[], recent: string[]): TopGuess[] {
  const raw = text.slice(piece.start, piece.end);
  const lead = raw.match(/^\s*/)![0];
  const core = raw.slice(lead.length);
  const space = lead.length ? ' ' : '';
  const capital = /^[A-Z]/.test(core);
  const style = (w: string) => space + (capital ? capitalize(w) : w);
  let pool: string[];
  if (piece.kind === 'nl') pool = [...NEWLINE_ALTS];
  else if (piece.kind === 'punct') pool = PUNCT_ALTS.slice();
  else if (piece.kind === 'cont') pool = SUFFIX_ALTS.slice();
  else if (piece.kind === 'num') pool = ['1', '2', 'two', 'ten', 'the', 'a'].map(style);
  else {
    const syn = SYNONYMS[core.toLowerCase()] ?? [];
    const fromText = Array.from({ length: 4 }, () => rng.pick(recent.length ? recent : FUNCTION_WORDS));
    const fn = Array.from({ length: 4 }, () => rng.pick(FUNCTION_WORDS));
    pool = [...syn, ...fromText, ...fn].map(style);
  }
  for (let n = pool.length - 1; n > 0; n--) {
    const m = Math.floor(rng.next() * (n + 1));
    [pool[n], pool[m]] = [pool[m], pool[n]];
  }
  const seen = new Set([raw.trim().toLowerCase() || raw]);
  const alts: string[] = [];
  for (const w of pool) {
    const key = w.trim().toLowerCase() || w;
    if (seen.has(key)) continue;
    seen.add(key);
    alts.push(w);
    if (alts.length === 5) break;
  }
  while (alts.length < 5) alts.push(style(['so', 'just', 'very', 'now', 'here'][alts.length]));
  const texts = rank <= 5 ? [...alts.slice(0, rank - 1), raw, ...alts.slice(rank - 1, 4)] : alts.slice(0, 5);
  return texts.map((t, n) => ({ text: t, p: round(probs[n], 4) }));
}

// ------------------------------------------------------------------------------------------
// per-token numbers

type Profile = { style: Style; target: number; ai: number };

function profileFor(text: string, rng: Rng): Profile {
  const words = countWords(text) || 1;
  const lower = text.toLowerCase();
  const cues = aiCueWords.reduce((n, w) => n + (lower.split(w).length - 1), 0);
  const density = (cues / words) * 100;
  const target = Math.min(1.06, Math.max(0.74, 1.01 - density * 0.07 + rng.range(-0.02, 0.02)));
  return { style: target < 0.9 ? 'ai' : 'human', target, ai: clamp01((1.02 - target) / 0.25) };
}

function paragraphProfiles(text: string, paras: [number, number][], rng: Rng): Profile[] {
  const norm = (s: string) => s.replace(/\s+/g, ' ').trim();
  const fixture = fixtures.find(f => norm(fixtureText(f)) === norm(text));
  if (fixture && fixture.paragraphs.length === paras.length) {
    return fixture.paragraphs.map(p => ({ style: p.style, target: p.target, ai: clamp01((1.02 - p.target) / 0.25) }));
  }
  return paras.map(([s, e]) => profileFor(text.slice(s, e), rng));
}

function drawRank(rng: Rng, w: number, kind: PieceKind): number {
  if (kind === 'nl') return rng.next() < 0.85 ? 1 : 2;
  if (kind === 'cont') return rng.next() < 0.9 ? 1 : rng.int(2, 3);
  if (kind === 'punct') return rng.next() < 0.62 + 0.2 * w ? 1 : rng.next() < 0.8 ? rng.int(2, 5) : rng.int(6, 30);
  const r = rng.next();
  const p1 = 0.38 + 0.3 * w;
  const p25 = 0.27 - 0.06 * w;
  const p640 = 0.2 - 0.12 * w;
  if (r < p1) return 1;
  if (r < p1 + p25) return rng.int(2, 5);
  if (r < p1 + p25 + p640) return rng.int(6, 40);
  return Math.round(Math.exp(rng.range(Math.log(41), Math.log(w > 0.5 ? 600 : 2400))));
}

function distribution(rng: Rng, w: number, kind: PieceKind): number[] {
  const p1 = kind === 'cont' ? rng.range(0.72, 0.99)
    : kind === 'nl' ? rng.range(0.55, 0.95)
    : kind === 'punct' ? rng.range(0.3, 0.88)
    : rng.range(0.12 + 0.22 * w, 0.5 + 0.38 * w);
  const probs = [p1];
  let rest = 1 - p1;
  for (let k = 1; k < 5; k++) {
    const p = Math.min(rest * rng.range(0.16, 0.42), probs[k - 1] * 0.94);
    probs.push(p);
    rest -= p;
  }
  return probs;
}

function entropyEstimate(probs: number[]): number {
  const tail = Math.max(1e-6, 1 - probs.reduce((a, b) => a + b, 0));
  return -probs.reduce((h, p) => h + p * Math.log(p), 0) + tail * (Math.log(1 / tail) + 3.4);
}

// ------------------------------------------------------------------------------------------
// the analysis

export type MockOptions = { calibrated: boolean; timing?: Result['timing_ms'] };

export function analyze(text: string, opts: MockOptions): Result {
  const rng = makeRng(hashString(text));
  const words = wordSpans(text);
  const wordCount = words.length;
  const paras = paragraphSpans(text);
  const sents = sentenceSpans(text, paras);
  const profiles = paragraphProfiles(text, paras, rng);
  const pieces = tokenize(text);

  const coreStart = (p: Piece) => {
    let c = p.start;
    while (c < p.end && /\s/.test(text[c])) c++;
    return c;
  };
  const paraOf = (pos: number) => {
    const n = paras.findIndex(([, e]) => pos < e);
    return n < 0 ? paras.length - 1 : n;
  };
  const sentenceOf = (pos: number) => {
    const n = sents.findIndex(([, e]) => pos < e);
    return n < 0 ? sents.length - 1 : n;
  };

  const recent: string[] = [];
  const raw = pieces.map(piece => {
    const pos = coreStart(piece);
    const para = piece.kind === 'nl' ? paraOf(piece.end) : paraOf(pos);
    const prof = profiles[para] ?? profiles[profiles.length - 1];
    const rank = drawRank(rng, prof.ai, piece.kind);
    const probs = distribution(rng, prof.ai, piece.kind);
    const pActual = rank <= 5 ? probs[rank - 1] : Math.max(2e-5, probs[4] * Math.pow(5 / rank, 1.05) * rng.range(0.6, 1));
    const top = topFive(rng, piece, text, rank, probs, recent);
    if (piece.kind === 'word') {
      const w = text.slice(piece.start, piece.end).trim().toLowerCase();
      if (w.length > 3) {
        recent.push(w);
        if (recent.length > 40) recent.shift();
      }
    }
    return {
      piece, para, rank, top,
      sentence: piece.kind === 'nl' ? sentenceOf(piece.end) : sentenceOf(pos),
      surprise: -Math.log(pActual),
      entropy: entropyEstimate(probs),
    };
  });

  // scale expected surprise per paragraph so each paragraph lands on its target score
  const factor = profiles.map((prof, p) => {
    // the first token is unscored (v1.1), so leave it out of the paragraph's target
    const rows = raw.filter((r, i) => i > 0 && r.para === p);
    const s = rows.reduce((a, r) => a + r.surprise, 0);
    const h = rows.reduce((a, r) => a + r.entropy, 0);
    return h > 0 ? s / (prof.target * h) : 1;
  });

  const centre = opts.calibrated
    ? (THRESHOLDS['150+'].ai_below + THRESHOLDS['150+'].human_above) / 2
    : (REFERENCE.ai_below + REFERENCE.human_above) / 2;

  const tokens: Token[] = raw.map((r, i) => {
    const expected = r.entropy * factor[r.para];
    return {
      i,
      start: r.piece.start,
      end: r.piece.end,
      text: text.slice(r.piece.start, r.piece.end),
      surprise: round(r.surprise, 3),
      expected_surprise: round(expected, 3),
      signal: round(Math.tanh((centre * expected - r.surprise) / 1.1), 3),
      signal_smooth: 0,
      rank: r.rank,
      top: r.top,
      sentence: r.sentence,
    } as Token;
  });
  // v1.1: the first token has no context, so it is never scored
  if (tokens.length) Object.assign(tokens[0], { surprise: null, expected_surprise: null, rank: null, top: [], signal: 0 });

  // triangular smoothing over neighbouring non-newline tokens
  const content = tokens.filter(t => !/^\s+$/.test(t.text));
  content.forEach((t, n) => {
    let sum = 0;
    let wsum = 0;
    for (let d = -3; d <= 3; d++) {
      const u = content[n + d];
      if (!u) continue;
      const w = 4 - Math.abs(d);
      sum += u.signal * w;
      wsum += w;
    }
    t.signal_smooth = round(sum / wsum, 3);
  });
  tokens.forEach((t, i) => {
    if (/^\s+$/.test(t.text)) t.signal_smooth = tokens[i + 1]?.signal_smooth ?? 0;
  });

  const scoreOf = (list: Token[]) => {
    const s = list.reduce((a, t) => a + (t.surprise ?? 0), 0);
    const e = list.reduce((a, t) => a + (t.expected_surprise ?? 0), 0);
    return e > 0 ? s / e : 1;
  };

  const bucket: LengthBucket = wordCount < 50 ? '20-49' : wordCount < 150 ? '50-149' : '150+';
  const thresholds = opts.calibrated ? THRESHOLDS[bucket] : null;
  const leanCut = thresholds ?? REFERENCE;
  const leanOf = (score: number): Lean => (score < leanCut.ai_below ? 'ai' : score > leanCut.human_above ? 'human' : 'neutral');

  const sentences: Sentence[] = sents.map(([start, end, paragraph], i) => {
    const idx = tokens.filter(t => t.sentence === i).map(t => t.i);
    const score = scoreOf(idx.map(n => tokens[n]));
    return {
      i, start, end, paragraph,
      token_start: idx.length ? idx[0] : 0,
      token_end: idx.length ? idx[idx.length - 1] + 1 : 0,
      score: round(score, 4),
      lean: leanOf(score),
    };
  });

  const paragraphs: Paragraph[] = paras.map(([start, end], i) => {
    const score = scoreOf(tokens.filter(t => sentences[t.sentence]?.paragraph === i));
    return { i, start, end, score: round(score, 4), lean: leanOf(score) };
  });

  const coreOf = (t: Token) => t.start + (t.text.length - t.text.trimStart().length);
  let segments: Segment[] = [];
  if (wordCount >= LIMITS.percent_min_words) {
    const starts: number[] = [];
    for (let s = 0; s + SEGMENT.window <= wordCount; s += SEGMENT.stride) starts.push(s);
    if (starts[starts.length - 1] + SEGMENT.window < wordCount) starts.push(wordCount - SEGMENT.window);
    segments = starts.map(ws => {
      const we = ws + SEGMENT.window;
      const start = words[ws][0];
      const end = words[we - 1][1];
      const score = scoreOf(tokens.filter(t => coreOf(t) >= start && coreOf(t) < end));
      return { start, end, word_start: ws, word_end: we, score: round(score, 4), flagged: opts.calibrated && score < SEGMENT.flag_below };
    });
  }

  let aiPercent: number | null = null;
  if (opts.calibrated && wordCount >= LIMITS.percent_min_words) {
    const flagged = new Set<number>();
    for (const s of segments) if (s.flagged) for (let w = s.word_start; w < s.word_end; w++) flagged.add(w);
    aiPercent = Math.round((100 * flagged.size) / wordCount);
  }

  const score = scoreOf(tokens);
  const band: Band = !thresholds ? 'uncalibrated'
    : score < thresholds.ai_below ? 'likely_ai'
    : score > thresholds.human_above ? 'likely_human'
    : 'uncertain';

  const counted = tokens.filter(t => t.rank != null && !/^\s+$/.test(t.text));
  // v1.1 #5: spread needs two sentences with at least 8 scored tokens, else null
  const sentenceScores = sentences
    .filter(s => tokens.slice(s.token_start, s.token_end).filter(t => t.rank != null).length >= 8)
    .map(s => s.score);
  const meanSentence = sentenceScores.reduce((a, b) => a + b, 0) / Math.max(1, sentenceScores.length);
  const stats = {
    top1_rate: round(counted.filter(t => t.rank === 1).length / counted.length, 3),
    top5_rate: round(counted.filter(t => (t.rank ?? 99) <= 5).length / counted.length, 3),
    mean_surprise: round(counted.reduce((a, t) => a + (t.surprise ?? 0), 0) / counted.length, 3),
    mean_expected_surprise: round(counted.reduce((a, t) => a + (t.expected_surprise ?? 0), 0) / counted.length, 3),
    sentence_score_spread:
      sentenceScores.length < 2
        ? null
        : round(Math.sqrt(sentenceScores.reduce((a, x) => a + (x - meanSentence) ** 2, 0) / sentenceScores.length), 3),
  };

  const lowConfidence = wordCount < LIMITS.percent_min_words;
  return {
    word_count: wordCount,
    token_count: tokens.length,
    model_pair: MODEL_PAIR,
    verdict: {
      band,
      label: LABELS[band],
      confidence: lowConfidence ? 'low' : 'normal',
      length_bucket: bucket,
      score: round(score, 4),
      thresholds,
      ai_percent: aiPercent,
      explanation: explanation(band, score, thresholds, lowConfidence),
    },
    reasons: reasons(stats, opts.calibrated),
    stats,
    tokens,
    sentences,
    paragraphs,
    segments,
    timing_ms: opts.timing ?? { queue: 0, load: 0, score: 1800 + tokens.length * 3 },
  };
}

// ------------------------------------------------------------------------------------------
// wording, ported from server/src/squint/reasons.py so the mock reads like the real thing

const LABELS: Record<Band, string> = {
  likely_human: 'Likely human',
  uncertain: 'Uncertain',
  likely_ai: 'Likely AI',
  uncalibrated: 'Not tuned yet',
};

function explanation(band: Band, score: number, t: { ai_below: number; human_above: number } | null, low: boolean): string {
  let text: string;
  if (band === 'uncalibrated' || !t) {
    text = `Squint hasn't been tuned for this model pair yet, so it gives no verdict. The raw score is ${score.toFixed(3)}; lower means more predictable, which is more AI-like.`;
  } else if (band === 'likely_ai') {
    text = `The text was much more predictable than the models expected: its score of ${score.toFixed(3)} is below ${t.ai_below.toFixed(3)}, a level few human texts of this length reached in tuning.`;
  } else if (band === 'likely_human') {
    text = `The text was about as surprising to the models as human writing usually is: its score of ${score.toFixed(3)} is above ${t.human_above.toFixed(3)}, where few AI texts of this length landed in tuning.`;
  } else {
    text = `The score of ${score.toFixed(3)} sits between ${t.ai_below.toFixed(3)} and ${t.human_above.toFixed(3)}, where human and AI texts overlap, so Squint won't call it either way.`;
  }
  if (low) text += ' With fewer than 150 words, treat this as a rough read.';
  return text;
}

const pct = (x: number) => `${Math.round(x * 100)}%`;
const STATS: [keyof typeof MEDIANS.human, string, string, (x: number) => string][] = [
  ['top1_rate', 'predictability', "{v} of words and word pieces were the model's first guess.", pct],
  ['top5_rate', 'top_five', "{v} were among the model's top five guesses.", pct],
  ['mean_surprise', 'surprise', 'Average surprise per token was {v} (lower means more predictable).', x => x.toFixed(2)],
  ['sentence_score_spread', 'consistency', 'Sentence-level scores varied by {v} from one sentence to the next.', x => x.toFixed(3)],
];

function reasons(stats: Result['stats'], calibrated: boolean): Reason[] {
  const out: (Reason & { order: number })[] = [];
  for (const [key, kind, sentence, fmt] of STATS) {
    const v = stats[key];
    if (v == null) continue;
    let text = sentence.replace('{v}', fmt(v));
    if (!calibrated) {
      out.push({ kind, text, weight: 'weak', order: 9 });
      continue;
    }
    const h = MEDIANS.human[key];
    const a = MEDIANS.ai[key];
    const t = (v - h) / (a - h);
    const side = t >= 0.5 ? 'AI' : 'human';
    const dist = Math.abs(t - 0.5);
    const weight = dist >= 0.5 ? 'strong' : dist >= 0.25 ? 'moderate' : 'weak';
    text += ` In our human samples the median is ${fmt(h)}; in AI samples, ${fmt(a)}.`;
    if (weight !== 'weak') text += ` That is closer to typical ${side} writing.`;
    out.push({ kind, text, weight, order: -dist });
  }
  return out.sort((x, y) => x.order - y.order).map(({ order: _order, ...r }) => r);
}

// ------------------------------------------------------------------------------------------
// accuracy report placeholder for the "How accurate is this?" page in development

export const MOCK_ACCURACY: Accuracy = {
  version: 'mock-2026-10-07',
  model_pair: MODEL_PAIR,
  held_out: { human: 420, ai: 450 },
  false_flag_rate: { overall: 0.008, non_native: 0.009, by_length: { '20-49': 0, '50-149': 0.006, '150+': 0.01 } },
  catch_rate: {
    overall: 0.52,
    // Mirrors the known gap in docs/known-gaps.md: ChatGPT mostly missed, Gemini untested (absent).
    by_source: { claude: 0.91, chatgpt: 0.083 },
    by_length: { '20-49': 0.2, '50-149': 0.61, '150+': 0.9 },
  },
  uncertain_rate: { human: 0.12, ai: 0.1 },
  notes: [
    'Development mock: placeholder numbers shaped like the known ChatGPT gap, not a calibration run.',
    'Edited or paraphrased AI text was not tested; expect misses there.',
  ],
};

function round(x: number, places: number) {
  const f = 10 ** places;
  return Math.round(x * f) / f;
}
function clamp01(x: number) {
  return Math.min(1, Math.max(0, x));
}
