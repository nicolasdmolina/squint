import { Button } from "@astryxdesign/core/Button";
import { useEffect, useState, type RefObject } from "react";
import { bandLine, gap, notes } from "../copy";
import { fmtInt, plural, words } from "../lib/format";
import type { Result, Segment } from "../types";
import { InfoIcon, RedoIcon } from "./Icons";

/** The reading: the band in words, the duochrome scale with its needle, then the facts in one row. */
export function Readout({
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
  const secs = (t.queue + t.load + t.score) / 1000;
  return (
    <section className="readout" aria-labelledby="checker-title">
      <header className="verdict-head">
        <h1
          id="checker-title"
          ref={titleRef}
          tabIndex={-1}
          className="verdict"
          data-band={v.band}
        >
          {v.label}
          {v.confidence === "low" && v.band !== "uncalibrated" && (
            <span className="sr-only">, low confidence</span>
          )}
        </h1>
        <p className="verdict-line">{bandLine[v.band]}</p>
        <p className="verdict-meta">
          {words(result.word_count)} &middot; checked in{" "}
          {secs < 10 ? secs.toFixed(1) : Math.round(secs)} seconds
          {v.confidence === "low" && v.band !== "uncalibrated" && (
            <>
              {" "}
              &middot;{" "}
              <span className="low-flag">
                Low confidence: under {fmtInt(percentMin)} words
              </span>
            </>
          )}
        </p>
      </header>

      <Duochrome score={v.score} thresholds={v.thresholds} />

      <dl className="facts">
        <div className="fact">
          <dt>AI-written share</dt>
          <dd>
            {v.ai_percent != null ? (
              <>
                <span className="fact-num">{v.ai_percent}%</span>
                <span className="fact-note">
                  of the text sits in passages that read as AI-like
                </span>
                <PercentStrip
                  segments={result.segments}
                  total={result.word_count}
                />
              </>
            ) : (
              <span className="fact-note">
                {v.band === "uncalibrated"
                  ? "Shown once Squint is tuned."
                  : `Needs ${fmtInt(percentMin)} words or more. This text has ${fmtInt(result.word_count)}.`}
              </span>
            )}
          </dd>
        </div>
        <div className="fact">
          <dt>Score</dt>
          <dd>
            <span className="fact-num">{v.score.toFixed(3)}</span>
            <span className="fact-note">
              {v.thresholds
                ? `Likely AI below ${v.thresholds.ai_below.toFixed(3)}, likely human above ${v.thresholds.human_above.toFixed(3)}`
                : "No cutoffs until Squint is tuned"}
            </span>
          </dd>
        </div>
      </dl>

      <p className="explain">{v.explanation}</p>

      <div className="caveat" role="note">
        <InfoIcon size={18} />
        <div>
          <p>
            <strong>{gap.title}</strong>{" "}
            {v.band === "uncalibrated" ? gap.shortUntuned : gap.short}{" "}
            {notes.evidence}
          </p>
          <p className="caveat-sub">{notes.stored}</p>
        </div>
      </div>

      <div className="readout-actions">
        <Button
          label="Check another text"
          variant="primary"
          onClick={onAnother}
        />
        <Button
          label="Edit this text"
          variant="secondary"
          icon={<RedoIcon size={16} />}
          onClick={onEdit}
        />
      </div>
    </section>
  );
}

function PercentStrip({
  segments,
  total,
}: {
  segments: Segment[];
  total: number;
}) {
  const flagged = segments.filter((s) => s.flagged);
  const spans: [number, number][] = [];
  for (const s of flagged) {
    const last = spans[spans.length - 1];
    if (last && s.word_start <= last[1])
      last[1] = Math.max(last[1], s.word_end);
    else spans.push([s.word_start, s.word_end]);
  }
  const caption = flagged.length
    ? `${flagged.length} of ${segments.length} overlapping ${plural(segments.length, "passage")} read as AI-like: ${spans
        .map(([a, b]) => `words ${fmtInt(a + 1)}–${fmtInt(b)}`)
        .join(", ")}.`
    : `None of the ${segments.length} overlapping ${plural(segments.length, "passage")} read as AI-like.`;
  return (
    <figure className="pstrip">
      <div className="pstrip-bar" aria-hidden="true">
        {spans.map(([a, b]) => (
          <span
            key={a}
            className="pstrip-fill"
            style={{
              left: `${(a / total) * 100}%`,
              width: `${((b - a) / total) * 100}%`,
            }}
          />
        ))}
      </div>
      <figcaption className="pstrip-cap">{caption}</figcaption>
    </figure>
  );
}

/**
 * The duochrome scale. Teal on the predictable side, rose on the surprising side, a neutral
 * overlap between; the needle eases to the score once. Position and labels carry the meaning,
 * colour repeats it.
 */
export function Duochrome({
  score,
  thresholds,
}: {
  score: number;
  thresholds: { ai_below: number; human_above: number } | null;
}) {
  const lo = Math.min(0.6, score - 0.05);
  const hi = Math.max(1.2, score + 0.05);
  const pct = (v: number) => ((v - lo) / (hi - lo)) * 100;
  const [placed, setPlaced] = useState(false);
  useEffect(() => {
    const id = requestAnimationFrame(() => setPlaced(true));
    return () => cancelAnimationFrame(id);
  }, []);
  const label = thresholds
    ? `Score ${score.toFixed(3)} on a scale from more predictable to more surprising. Below ${thresholds.ai_below.toFixed(3)} reads as likely AI, above ${thresholds.human_above.toFixed(3)} as likely human, and between is uncertain.`
    : `Score ${score.toFixed(3)} on a scale from more predictable to more surprising. No cutoffs yet, because Squint isn't tuned.`;
  const zones = thresholds
    ? [
        { z: "ai", label: "Likely AI", from: lo, to: thresholds.ai_below },
        {
          z: "mid",
          label: "Uncertain",
          from: thresholds.ai_below,
          to: thresholds.human_above,
        },
        {
          z: "hu",
          label: "Likely human",
          from: thresholds.human_above,
          to: hi,
        },
      ]
    : [];
  const at = pct(score);
  return (
    <figure className="duo" role="img" aria-label={label}>
      <div className="duo-field" data-untuned={!thresholds || undefined}>
        {zones.map((zone) => (
          <span
            key={zone.z}
            className={`duo-zone duo-${zone.z}`}
            data-here={score >= zone.from && score < zone.to ? true : undefined}
            style={{
              left: `${pct(zone.from)}%`,
              width: `${pct(zone.to) - pct(zone.from)}%`,
            }}
          />
        ))}
        <span
          className="duo-needle"
          data-edge={at < 8 ? "start" : at > 92 ? "end" : undefined}
          style={{ left: placed ? `${at}%` : "50%" }}
        >
          <span className="duo-value">{score.toFixed(3)}</span>
        </span>
      </div>
      {zones.length > 0 && (
        <div className="duo-labels" aria-hidden="true">
          {zones.map((zone) => {
            const mid = (pct(zone.from) + pct(zone.to)) / 2;
            const edge =
              zone.z === "ai" && mid < 14
                ? "start"
                : zone.z === "hu" && mid > 86
                  ? "end"
                  : undefined;
            return (
              <span
                key={zone.z}
                className={`duo-label duo-label-${zone.z}`}
                data-here={
                  score >= zone.from && score < zone.to ? true : undefined
                }
                data-align={edge}
                style={{
                  left:
                    edge === "start" ? 0 : edge === "end" ? "100%" : `${mid}%`,
                }}
              >
                {zone.label}
              </span>
            );
          })}
        </div>
      )}
      <div className="duo-ends" aria-hidden="true">
        <span>More predictable</span>
        <span>More surprising</span>
      </div>
      {!thresholds && (
        <p className="duo-none">
          No cutoffs until Squint is tuned, so the scale has no zones.
        </p>
      )}
    </figure>
  );
}
