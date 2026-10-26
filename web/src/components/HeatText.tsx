import { memo, type ReactNode } from 'react';
import type { Paragraph, Result } from '../types';
import { heat, level, tone, type Word } from '../lib/words';

/**
 * The submitted text, reprinted exactly, with every word wrapped in its signal.
 * Rendered once per result and view; the active word is styled imperatively by the parent so
 * hovering across 2,500 words never re-renders this tree.
 */
export const HeatText = memo(function HeatText({
  text,
  result,
  words,
  smooth,
}: {
  text: string;
  result: Result;
  words: Word[];
  smooth: boolean;
}) {
  const paragraphs: Paragraph[] = result.paragraphs.length
    ? result.paragraphs
    : [{ i: 0, start: 0, end: text.length, score: result.verdict.score, lean: 'neutral' }];

  let wi = 0;
  return (
    <>
      {paragraphs.map(p => {
        const parts: ReactNode[] = [];
        let pos = p.start;
        let prev: number | null = null;
        while (wi < words.length && words[wi].start < p.end) {
          const w = words[wi];
          if (w.start >= p.start) {
            // A token glued to the one before it ("Wi-Fi", "end.") must not bleed its shading over that token's letters.
            const join = parts.length > 0 && w.start === pos ? true : undefined;
            const v = smooth ? w.smooth : w.signal;
            // In the smoothed view the two faintest steps draw nothing, so they never join or extend a run.
            const seen = smooth && level(v) <= 2 ? 0 : v;
            if (w.start > pos) {
              const gap = text.slice(pos, w.start);
              // A space between two words leaning the same way carries the weaker mark, so a phrase reads as one stroke.
              const same = prev != null && /^[ \t]+$/.test(gap) && tone(prev) === tone(seen) && tone(seen) !== 'nu';
              parts.push(
                same ? (
                  <span key={`g${w.g}`} className="w-gap" data-heat={heat(Math.abs(prev!) < Math.abs(seen) ? prev! : seen)}>
                    {gap}
                  </span>
                ) : (
                  gap
                ),
              );
            }
            // Punctuation carries a mark only as the tail of the word it is glued to, so a run never opens on the
            // comma or full stop that closes the clause before it.
            const pv: number = w.punct && !(join && prev != null && tone(prev) === tone(seen)) ? 0 : v;
            prev = w.punct ? (pv === 0 ? 0 : seen) : seen;
            parts.push(
              w.punct ? (
                <span key={w.g} className="w is-punct" data-heat={heat(pv)} data-join={join}>
                  {w.text}
                </span>
              ) : (
                <span
                  key={w.g}
                  className="w"
                  data-heat={heat(v)}
                  data-join={join}
                  data-n={w.n}
                  role="button"
                  tabIndex={w.n === 0 ? 0 : -1}
                >
                  {w.text}
                </span>
              ),
            );
            pos = Math.min(w.end, p.end);
          }
          wi++;
        }
        if (pos < p.end) parts.push(text.slice(pos, p.end));
        return (
          <p className="para" key={p.i} data-lean={p.lean}>
            {parts}
          </p>
        );
      })}
    </>
  );
});
