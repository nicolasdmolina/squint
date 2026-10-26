import { fmtInt } from '../lib/format';
import type { Status } from '../types';
import { CheckIcon } from './Icons';

/**
 * What the reading can say at this length, as margin stops that tick off as the text grows.
 * The guide sentence (screen readers, and the textarea's description) says the same in words,
 * so this list stays out of the accessibility tree.
 */
export function Stops({ n, limits, verdictAt }: { n: number; limits: Status['limits']; verdictAt: number | null }) {
  const { min_words: min, percent_min_words: pct, max_words: max } = limits;
  const over = n > max;
  const stops = [
    ...(verdictAt != null && verdictAt > min ? [{ v: min, label: 'Word marks' }] : []),
    { v: verdictAt ?? min, label: 'Verdict' },
    { v: pct, label: 'AI-written share' },
  ];
  return (
    <ol className="stops" aria-hidden="true">
      {stops.map(s => (
        <li key={s.label} className="stop" data-reached={n >= s.v && !over ? true : undefined}>
          <span className="stop-mark">{n >= s.v && !over && <CheckIcon size={14} />}</span>
          <span className="stop-label">{s.label}</span>
          <span className="stop-num">{fmtInt(s.v)}</span>
        </li>
      ))}
      <li className="stop is-limit" data-over={over || undefined}>
        <span className="stop-mark" />
        <span className="stop-label">{over ? `${fmtInt(n - max)} over the limit` : 'Limit'}</span>
        <span className="stop-num">{fmtInt(max)}</span>
      </li>
    </ol>
  );
}
