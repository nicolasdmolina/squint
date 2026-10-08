import { Button } from '@astryxdesign/core/Button';
import type { CSSProperties } from 'react';
import { bandLine, notes } from '../copy';
import { fmtInt, plural, words } from '../lib/format';
import type { Band, Result, Segment } from '../types';
import { InfoIcon, RedoIcon } from './Icons';

/** The printed reading: one ruled grid, label column on the left like an instrument slip. */
export function Readout({
  result,
  percentMin,
  onAnother,
  onEdit,
}: {
  result: Result;
  percentMin: number;
  onAnother: () => void;
  onEdit: () => void;
}) {
  const v = result.verdict;
  return (
    <section className="readout" aria-labelledby="checker-title">
      <dl className="rows">
        <div className="row row-band">
          <dt className="row-label">Reading</dt>
          <dd className="row-body">
            <div className="band-line">
              <BandMeter band={v.band} />
              <p className="band" data-band={v.band}>
                {v.label}
              </p>
              {v.confidence === 'low' && (
                <span className="low-flag">
                  <InfoIcon size={16} />
                  Low confidence: under {fmtInt(percentMin)} words
                </span>
              )}
            </div>
            <p className="band-sub">{bandLine[v.band]}</p>
            <p className="explain">{v.explanation}</p>
          </dd>
        </div>

        <div className="row row-share">
          <dt className="row-label">AI-written share</dt>
          <dd className="row-body">
            {v.ai_percent != null ? (
              <>
                <p className="share">
                  <span className="share-num">{v.ai_percent}%</span>
                  <span className="share-cap">of this text looks AI-written</span>
                </p>
                <PercentStrip segments={result.segments} total={result.word_count} />
              </>
            ) : (
              <p className="share-none">
                <span className="share-none-title">No percentage for this text.</span>{' '}
                {v.band === 'uncalibrated'
                  ? 'The share appears once Squint is tuned.'
                  : `It needs ${fmtInt(percentMin)} words or more, so there are enough full passages to compare. This text has ${fmtInt(result.word_count)}.`}
              </p>
            )}
          </dd>
        </div>

        <div className="row row-score">
          <dt className="row-label">Score</dt>
          <dd className="row-body">
            <ScoreScale score={v.score} thresholds={v.thresholds} />
          </dd>
        </div>

        <div className="row row-note">
          <dt className="row-label">Keep in mind</dt>
          <dd className="row-body">
            <p className="note-strong">{notes.evidence}</p>
            <p className="note">{notes.stored}</p>
          </dd>
        </div>
      </dl>
      <div className="readout-actions">
        <Button label="Check another text" variant="primary" onClick={onAnother} />
        <Button label="Edit this text" variant="secondary" icon={<RedoIcon size={16} />} onClick={onEdit} />
      </div>
    </section>
  );
}

/** Three cells, AI-like to human-like; the band fills one. Position carries it, colour repeats it. */
function BandMeter({ band }: { band: Band }) {
  const cells: { key: Band; label: string }[] = [
    { key: 'likely_ai', label: 'Likely AI' },
    { key: 'uncertain', label: 'Uncertain' },
    { key: 'likely_human', label: 'Likely human' },
  ];
  return (
    <span className="band-meter" aria-hidden="true">
      {cells.map(c => (
        <span key={c.key} className="band-cell" data-cell={c.key} data-on={band === c.key || undefined} />
      ))}
    </span>
  );
}

function PercentStrip({ segments, total }: { segments: Segment[]; total: number }) {
  const flagged = segments.filter(s => s.flagged);
  const spans: [number, number][] = [];
  for (const s of flagged) {
    const last = spans[spans.length - 1];
    if (last && s.word_start <= last[1]) last[1] = Math.max(last[1], s.word_end);
    else spans.push([s.word_start, s.word_end]);
  }
  const caption = flagged.length
    ? `${flagged.length} of ${segments.length} overlapping ${plural(segments.length, 'passage')} flagged: ${spans
        .map(([a, b]) => `words ${fmtInt(a + 1)}–${fmtInt(b)}`)
        .join(', ')}.`
    : `None of the ${segments.length} overlapping ${plural(segments.length, 'passage')} were flagged.`;
  return (
    <figure className="pstrip">
      <div className="pstrip-bar" aria-hidden="true">
        {spans.map(([a, b]) => (
          <span key={a} className="pstrip-fill" style={{ left: `${(a / total) * 100}%`, width: `${((b - a) / total) * 100}%` }} />
        ))}
      </div>
      <div className="pstrip-axis" aria-hidden="true">
        <span>Word 1</span>
        <span>{words(total)}</span>
      </div>
      <figcaption className="pstrip-cap">{caption}</figcaption>
    </figure>
  );
}

/**
 * Where a zone's label may sit. In the zone the needle crosses, the label keeps to the wider side
 * of the needle with a small gap, and hides (by container query) when that side is too narrow to
 * hold it, so the needle never strikes through the lettering.
 */
function labelSlot(from: number, to: number, score: number): CSSProperties {
  if (score <= from || score >= to) return { left: 0, right: 0 };
  const at = ((score - from) / (to - from)) * 100;
  return at >= 50 ? { left: 0, right: `calc(${100 - at}% + 5px)` } : { left: `calc(${at}% + 5px)`, right: 0 };
}

/** The raw score on a small rule: cutoffs as engraved ticks, the reading as a needle. */
export function ScoreScale({ score, thresholds }: { score: number; thresholds: { ai_below: number; human_above: number } | null }) {
  const lo = Math.min(0.6, score - 0.04);
  const hi = Math.max(1.2, score + 0.04);
  const x = (v: number) => `${((v - lo) / (hi - lo)) * 100}%`;
  const label = thresholds
    ? `Score ${score.toFixed(3)}. Below ${thresholds.ai_below.toFixed(3)} reads as likely AI; above ${thresholds.human_above.toFixed(3)} reads as likely human; between is uncertain.`
    : `Score ${score.toFixed(3)}. No cutoffs yet, because Squint isn't tuned.`;
  return (
    <div className="scale" role="img" aria-label={label}>
      <div className="scale-value" style={{ left: x(score) }}>
        {score.toFixed(3)}
      </div>
      <div className="scale-bar">
        {thresholds
          ? (
              [
                { z: 'ai', label: 'Likely AI', from: lo, to: thresholds.ai_below },
                { z: 'mid', label: 'Uncertain', from: thresholds.ai_below, to: thresholds.human_above },
                { z: 'hu', label: 'Likely human', from: thresholds.human_above, to: hi },
              ] as const
            ).map(zone => (
              <span key={zone.z} className={`zone zone-${zone.z}`} style={{ left: x(zone.from), width: `calc(${x(zone.to)} - ${x(zone.from)})` }}>
                <span className="zone-slot" data-z={zone.z} style={labelSlot(zone.from, zone.to, score)}>
                  <span className="zone-label">{zone.label}</span>
                </span>
              </span>
            ))
          : null}
        <span className="needle" style={{ left: x(score) }} />
      </div>
      <div className="scale-ticks">
        {thresholds && (
          <>
            <span className="cut" style={{ left: x(thresholds.ai_below) }}>
              {thresholds.ai_below.toFixed(3)}
            </span>
            <span className="cut" style={{ left: x(thresholds.human_above) }}>
              {thresholds.human_above.toFixed(3)}
            </span>
          </>
        )}
      </div>
      <div className="scale-ends">
        <span>More predictable</span>
        <span>More surprising</span>
      </div>
      {!thresholds && <p className="cut-none">No cutoffs until Squint is tuned.</p>}
    </div>
  );
}
