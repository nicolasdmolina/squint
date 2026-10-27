import type { Segment } from '../types';

export type Passage = { start: number; end: number; ws: number; we: number };

/** Flagged 150-word windows, merged where the overlapping windows touch: each becomes one margin bracket. */
export function flaggedPassages(segments: Segment[]): Passage[] {
  const out: Passage[] = [];
  for (const seg of segments.filter(x => x.flagged)) {
    const last = out[out.length - 1];
    if (last && seg.start <= last.end) {
      last.end = Math.max(last.end, seg.end);
      last.we = Math.max(last.we, seg.word_end);
    } else out.push({ start: seg.start, end: seg.end, ws: seg.word_start, we: seg.word_end });
  }
  return out;
}
