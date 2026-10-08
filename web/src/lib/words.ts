import type { Lean, Result, TopGuess } from '../types';

/**
 * A run of tokens shown as one word in the printout. Tokens carry their leading whitespace;
 * a new word starts at whitespace, at a punctuation-only token, or right after one.
 * Punctuation is tinted like everything else but is not a stop for the inspector.
 */
export type Word = {
  /** index in `words` */
  g: number;
  /** index among interactive (non-punctuation) words, or -1 */
  n: number;
  start: number;
  end: number;
  text: string;
  punct: boolean;
  tokens: number[];
  /** mean raw signal of the pieces */
  signal: number;
  /** mean smoothed signal of the pieces */
  smooth: number;
  /** summed over scored pieces; null when no piece was scored (the text's first token) */
  surprise: number | null;
  expected: number | null;
  /** rank and guesses of the first scored piece; null when unscored */
  rank: number | null;
  top: TopGuess[];
  /** index into result.tokens of the piece that rank and top describe */
  lead: number;
  sentence: number;
  paragraph: number;
  /** 1-based position among whitespace-separated words, the way the server counts word_count */
  ord: number;
};

const PUNCT_ONLY = /^[^\p{L}\p{N}]+$/u;
const WORDISH = /[\p{L}\p{N}]/u;

export function buildWords(result: Result, text: string): { words: Word[]; stops: Word[] } {
  const words: Word[] = [];
  let current: Word | null = null;
  let breakNext = true;
  const paragraphOfSentence = new Map(result.sentences.map(s => [s.i, s.paragraph]));

  for (const t of result.tokens) {
    const raw = text.slice(t.start, t.end);
    const lead = raw.length - raw.trimStart().length;
    // Some tokenizers fold the following whitespace into a token (".\n\n"); keep it out of the word.
    const core = raw.slice(lead).trimEnd();
    const trail = raw.length - lead - core.length > 0;
    const end = t.start + lead + core.length;
    if (!core) {
      breakNext = true;
      continue;
    }
    let punct = PUNCT_ONLY.test(core);
    // Punctuation inside a word ("Wi-Fi", "1,000") stays part of it rather than splitting it in two.
    const inner = punct && lead === 0 && !trail && !breakNext && !!current && !current.punct && WORDISH.test(text[t.end] ?? '');
    if (inner) punct = false;
    const startsWord = !current || breakNext || lead > 0 || punct || current.punct;
    if (startsWord) {
      current = {
        g: words.length,
        n: -1,
        start: t.start + lead,
        end,
        text: '',
        punct,
        tokens: [t.i],
        signal: t.signal,
        smooth: t.signal_smooth,
        surprise: t.surprise,
        expected: t.expected_surprise,
        rank: t.rank,
        top: t.top,
        lead: t.i,
        sentence: t.sentence,
        paragraph: paragraphOfSentence.get(t.sentence) ?? 0,
        ord: 0,
      };
      words.push(current);
    } else if (current) {
      current.end = end;
      current.tokens.push(t.i);
      current.signal += t.signal;
      current.smooth += t.signal_smooth;
      if (t.surprise != null) current.surprise = (current.surprise ?? 0) + t.surprise;
      if (t.expected_surprise != null) current.expected = (current.expected ?? 0) + t.expected_surprise;
      if (current.rank == null && t.rank != null) {
        current.rank = t.rank;
        current.top = t.top;
        current.lead = t.i;
      }
    }
    breakNext = trail;
  }

  // whitespace-run starts, to number words the same way the server's word_count does
  const runStarts: number[] = [];
  for (const m of text.matchAll(/\S+/g)) runStarts.push(m.index ?? 0);
  let run = 0;

  const stops: Word[] = [];
  for (const w of words) {
    while (run < runStarts.length && runStarts[run] <= w.start) run++;
    w.ord = Math.max(1, run);
    const k = w.tokens.length;
    w.signal /= k;
    w.smooth /= k;
    w.text = text.slice(w.start, w.end);
    if (!w.punct) {
      w.n = stops.length;
      stops.push(w);
    }
  }
  return { words, stops };
}

/** 0 = neutral, 1-4 = strength bands of |signal|. */
export function level(v: number): 0 | 1 | 2 | 3 | 4 {
  const a = Math.abs(v);
  if (a < 0.15) return 0;
  if (a < 0.35) return 1;
  if (a < 0.55) return 2;
  if (a < 0.75) return 3;
  return 4;
}

export type Tone = 'ai' | 'hu' | 'nu';
export const tone = (v: number): Tone => (level(v) === 0 ? 'nu' : v > 0 ? 'ai' : 'hu');

/** data-heat attribute value, e.g. "ai3", "hu1", "nu0" */
export const heat = (v: number) => `${tone(v)}${level(v)}`;

export const leanWord = (v: number) =>
  tone(v) === 'ai' ? 'AI-like' : tone(v) === 'hu' ? 'human-like' : 'no lean';

export const leanText = (lean: Lean) =>
  lean === 'ai' ? 'Leans AI-like' : lean === 'human' ? 'Leans human-like' : 'No clear lean';

/** Share of interactive words in each direction (by the view in use). */
export function leanShares(stops: Word[], smooth: boolean) {
  let ai = 0;
  let hu = 0;
  for (const w of stops) {
    const t = tone(smooth ? w.smooth : w.signal);
    if (t === 'ai') ai++;
    else if (t === 'hu') hu++;
  }
  const n = Math.max(1, stops.length);
  return { ai: ai / n, hu: hu / n };
}

/** Index of the interactive word whose range contains or follows a character offset. */
export function stopAt(stops: Word[], offset: number): number {
  let lo = 0;
  let hi = stops.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (stops[mid].end <= offset) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}
