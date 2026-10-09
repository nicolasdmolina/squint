import { fmtInt } from '../lib/format';
import type { Status } from '../types';

/**
 * How much the reading can say at this length: a track with three stops, like a slider with
 * named detents. Piecewise, so the short-text stops get room to read. The guide line below
 * carries the same facts in words, so this stays out of the accessibility tree.
 */
export function LengthMeter({ n, limits }: { n: number; limits: Status['limits'] }) {
  const { min_words: min, percent_min_words: pct, max_words: max } = limits;
  const pos = (v: number) => {
    if (v <= min) return (v / min) * 0.14;
    if (v <= pct) return 0.14 + ((v - min) / (pct - min)) * 0.3;
    return Math.min(1, 0.44 + ((v - pct) / (max - pct)) * 0.56);
  };
  const stops = [
    { v: min, label: 'Verdict' },
    { v: pct, label: 'AI-written share' },
    { v: max, label: 'Limit' },
  ];
  const over = n > max;
  return (
    <div className={`meter${over ? ' is-over' : ''}`} aria-hidden="true">
      <div className="meter-track">
        <span className="meter-fill" style={{ transform: `scaleX(${pos(n)})` }} />
        {stops.map(s => (
          <span key={s.v} className={`meter-stop${n >= s.v ? ' is-reached' : ''}`} style={{ left: `${pos(s.v) * 100}%` }} />
        ))}
      </div>
      <div className="meter-labels">
        {stops.map((s, i) => (
          <span
            key={s.v}
            className={`meter-label${n >= s.v ? ' is-reached' : ''}${i === stops.length - 1 ? ' is-end' : ''}`}
            style={{ left: `${pos(s.v) * 100}%` }}
          >
            {s.label} <span className="meter-num">{fmtInt(s.v)}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
