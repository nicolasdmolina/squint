import { fmtInt } from '../lib/format';
import type { Status } from '../types';

/**
 * The word budget drawn as a measuring rule with three detents, like tape length against
 * running time. The scale is piecewise so the short-text detents get room to read.
 */
export function CapacityRule({ n, limits }: { n: number; limits: Status['limits'] }) {
  const { min_words: min, percent_min_words: pct, max_words: max } = limits;
  const pos = (v: number) => {
    if (v <= min) return (v / min) * 0.1;
    if (v <= pct) return 0.1 + ((v - min) / (pct - min)) * 0.25;
    return Math.min(1, 0.35 + ((v - pct) / (max - pct)) * 0.65);
  };
  const minor: number[] = [];
  for (let v = 5; v < min; v += 5) minor.push(v);
  for (let v = min + 10; v < pct; v += 10) minor.push(v);
  for (let v = pct + 50; v < max; v += 50) minor.push(v);
  const major = [500, 1000, 1500, 2000].filter(v => v > pct && v < max);
  const detents = [
    { v: min, label: 'verdict' },
    { v: pct, label: 'AI-written share' },
    { v: max, label: 'limit' },
  ];
  const over = n > max;

  return (
    <div className={`cap${over ? ' is-over' : ''}`} aria-hidden="true">
      <svg className="cap-svg" width="100%" height="22" preserveAspectRatio="none">
        <line className="cap-base" x1="0" x2="100%" y1="14.5" y2="14.5" />
        {minor.map(v => (
          <line key={v} className="cap-minor" x1={`${pos(v) * 100}%`} x2={`${pos(v) * 100}%`} y1="11" y2="14.5" />
        ))}
        {major.map(v => (
          <line key={v} className="cap-major" x1={`${pos(v) * 100}%`} x2={`${pos(v) * 100}%`} y1="8" y2="14.5" />
        ))}
        <rect className="cap-fill" x="0" y="13" width="100%" height="3" style={{ transform: `scaleX(${pos(n)})` }} />
        {detents.map(d => (
          <line
            key={d.v}
            className={`cap-detent${n >= d.v ? ' is-reached' : ''}`}
            x1={`${Math.min(pos(d.v) * 100, 99.85)}%`}
            x2={`${Math.min(pos(d.v) * 100, 99.85)}%`}
            y1="3"
            y2="22"
          />
        ))}
      </svg>
      <div className="cap-labels">
        {detents.map(d => (
          <span
            key={d.v}
            className={`cap-label${n >= d.v ? ' is-reached' : ''}${d.v === max ? ' is-end' : ''}`}
            style={{ left: `${pos(d.v) * 100}%` }}
          >
            <b>{fmtInt(d.v)}</b> {d.label}
          </span>
        ))}
      </div>
    </div>
  );
}
