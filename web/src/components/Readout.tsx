import { Button } from '@astryxdesign/core/Button';
import { useEffect, useState, type RefObject } from 'react';
import { bandLine, gap, gapBinoculars, notes } from '../copy';
import { fmtInt, words } from '../lib/format';
import type { Result } from '../types';

/** The editor's note at the head of the galley: how long, the band in large type, one plain sentence. */
export function VerdictHead({
  result,
  percentMin,
  titleRef,
  onAnother,
  onEdit,
}: {
  result: Result;
  percentMin: number;
  titleRef: RefObject<HTMLHeadingElement | null>;
  onAnother: () => void;
  onEdit: () => void;
}) {
  const v = result.verdict;
  const t = result.timing_ms;
  const noVerdict = v.band === 'uncalibrated' || v.band === 'too_short';
  const low = v.confidence === 'low' && !noVerdict;
  const secs = (t.queue + t.load + t.score) / 1000;
  return (
    <header className="verdict-head">
      <p className="verdict-meta">
        {words(result.word_count)} &middot; {secs < 10 ? secs.toFixed(1) : Math.round(secs)} s
        {low && <> &middot; rough read under {fmtInt(percentMin)} words</>}
      </p>
      <h1 id="checker-title" ref={titleRef} tabIndex={-1} className="verdict" data-band={v.band}>
        {v.label}
        {low && <span className="sr-only">, low confidence</span>}
      </h1>
      <p className="verdict-line">{bandLine(v.band, v.classifier?.min_words ?? 50)}</p>
      {v.detector !== 'classifier' && <Duochrome score={v.score} thresholds={v.thresholds} />}
      <div className="verdict-actions">
        <Button label="Check another" variant="primary" onClick={onAnother} />
        <Button label="Edit text" variant="secondary" onClick={onEdit} />
      </div>
    </header>
  );
}

/** The margin's opening: every figure in one tabular column. */
export function MarginFacts({ result }: { result: Result }) {
  const v = result.verdict;
  const s = result.stats;
  const pct = (x: number) => `${Math.round(x * 100)}%`;
  const rows: [string, string][] = [
    ['AI-written share', v.ai_percent != null ? `${v.ai_percent}%` : '—'],
    ['Words', fmtInt(result.word_count)],
    ["Model's first guess", pct(s.top1_rate)],
    ['In its top five', pct(s.top5_rate)],
    ['Predictability', v.score.toFixed(3)],
  ];
  return (
    <>
      <table className="figures">
        <caption className="sr-only">Figures for this text</caption>
        <tbody>
          {rows.map(([k, val]) => (
            <tr key={k}>
              <th scope="row">{k}</th>
              <td>{val}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {v.ai_percent == null && v.band !== 'uncalibrated' && v.band !== 'too_short' && (
        <p className="margin-quiet">The AI-written share starts at 150 words.</p>
      )}
    </>
  );
}

/** The known blind spot and the privacy line, once, at the foot of the margin. */
export function MarginGap({ result }: { result: Result }) {
  const known = result.verdict.detector === 'classifier' ? gap : gapBinoculars;
  return (
    <>
      <div className="query">
        <p className="query-tag">Known gap</p>
        <p className="query-text">
          {known.margin} A &ldquo;Likely human&rdquo; reading doesn&rsquo;t clear a text.
        </p>
      </div>
      <p className="margin-quiet">{notes.stored}</p>
    </>
  );
}

/**
 * The Binoculars-only fallback (no trained detector): the score on a ruler with its two
 * cutoffs. Position and labels carry the meaning; the pencil colours repeat it.
 */
export function Duochrome({ score, thresholds }: { score: number; thresholds: { ai_below: number; human_above: number } | null }) {
  const lo = Math.min(0.6, score - 0.05);
  const hi = Math.max(1.2, score + 0.05);
  const pct = (x: number) => ((x - lo) / (hi - lo)) * 100;
  const [placed, setPlaced] = useState(false);
  useEffect(() => {
    const id = requestAnimationFrame(() => setPlaced(true));
    return () => cancelAnimationFrame(id);
  }, []);
  const label = thresholds
    ? `Score ${score.toFixed(3)}. Below ${thresholds.ai_below.toFixed(3)} reads as likely AI, above ${thresholds.human_above.toFixed(3)} as likely human, between is uncertain.`
    : `Score ${score.toFixed(3)}. No cutoffs yet, because Squint isn't tuned.`;
  const at = pct(score);
  return (
    <figure className="ruler" role="img" aria-label={label}>
      <div className="ruler-track">
        {thresholds && (
          <>
            <span className="ruler-zone is-ai" style={{ left: 0, width: `${pct(thresholds.ai_below)}%` }} />
            <span className="ruler-zone is-hu" style={{ left: `${pct(thresholds.human_above)}%`, right: 0 }} />
            <span className="ruler-cut" style={{ left: `${pct(thresholds.ai_below)}%` }} />
            <span className="ruler-cut" style={{ left: `${pct(thresholds.human_above)}%` }} />
          </>
        )}
        <span className="ruler-needle" style={{ left: placed ? `${at}%` : '50%' }}>
          <span className="ruler-value">{score.toFixed(3)}</span>
        </span>
      </div>
      <div className="ruler-ends" aria-hidden="true">
        <span>Likely AI</span>
        {thresholds && <span>Uncertain</span>}
        <span>Likely human</span>
      </div>
    </figure>
  );
}
