import { useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { DOWNLOAD_HREF } from '../copy';
import { fmtInt } from '../lib/format';
import { useMedia } from '../lib/hooks';
import { flaggedPassages } from '../lib/passages';
import type { Result } from '../types';
import { ArrowRightIcon } from './Icons';
import { MarginFacts, MarginGap } from './Readout';

/**
 * A preview result (contract v1.3): the classifier's verdict and its flagged passages on the
 * proof, with no word-level data. Same galley and margin as the full result, minus the word lens.
 */
export function PreviewEvidence({ result, text, head }: { result: Result; text: string; head: ReactNode }) {
  const passages = useMemo(() => flaggedPassages(result.segments), [result.segments]);
  const reduceMotion = useMedia('(prefers-reduced-motion: reduce)');
  const printRef = useRef<HTMLDivElement>(null);
  const [current, setCurrent] = useState<number | null>(null);

  // Paragraphs from the text itself, each cut where a flagged passage starts or ends.
  const paras = useMemo(() => {
    const out: { key: number; parts: { s: string; p: number | null }[] }[] = [];
    const re = /[^\n]+/g;
    let m: RegExpExecArray | null;
    while ((m = re.exec(text))) {
      if (!m[0].trim()) continue;
      const ps = m.index;
      const pe = ps + m[0].length;
      const cuts = new Set([ps, pe]);
      for (const p of passages) {
        if (p.start > ps && p.start < pe) cuts.add(p.start);
        if (p.end > ps && p.end < pe) cuts.add(p.end);
      }
      const at = [...cuts].sort((a, b) => a - b);
      const parts = at.slice(0, -1).map((from, i) => {
        const to = at[i + 1];
        const hit = passages.findIndex(p => p.start <= from && p.end >= to);
        return { s: text.slice(from, to), p: hit < 0 ? null : hit };
      });
      out.push({ key: ps, parts });
    }
    return out;
  }, [text, passages]);

  // Each bracket spans its passage's first to last line.
  const [brackets, setBrackets] = useState<{ top: number; height: number }[]>([]);
  useLayoutEffect(() => {
    const box = printRef.current;
    if (!box || !passages.length) return setBrackets([]);
    const measure = () => {
      const b = box.getBoundingClientRect();
      setBrackets(
        passages.map((_, i) => {
          const marks = box.querySelectorAll<HTMLElement>(`mark[data-p="${i}"]`);
          if (!marks.length) return { top: 0, height: 0 };
          const first = marks[0].getClientRects()[0];
          const lastRects = marks[marks.length - 1].getClientRects();
          const last = lastRects[lastRects.length - 1];
          return { top: first.top - b.top, height: last.bottom - first.top };
        }),
      );
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(box);
    void document.fonts?.ready.then(measure);
    return () => ro.disconnect();
  }, [passages, paras]);

  const showPassage = (i: number) => {
    setCurrent(i);
    const first = printRef.current?.querySelector<HTMLElement>(`mark[data-p="${i}"]`);
    first?.scrollIntoView({ block: 'center', behavior: reduceMotion ? 'auto' : 'smooth' });
  };

  return (
    <div className="proof is-result is-preview">
      <section className="galley" aria-labelledby="checker-title">
        {head}
        {passages.length > 0 && (
          <div className="galley-tools">
            <ul className="legend" aria-label="Marks">
              <li>
                <span className="legend-sample passage">text</span>
                Reads as AI-written
              </li>
            </ul>
          </div>
        )}
        <div className="printout" ref={printRef} role="group" aria-label="Your text">
          {paras.map(para => (
            <p className="para" key={para.key}>
              {para.parts.map((part, j) =>
                part.p == null ? (
                  part.s
                ) : (
                  <mark key={j} className="passage" data-p={part.p} data-current={current === part.p || undefined}>
                    {part.s}
                  </mark>
                ),
              )}
            </p>
          ))}
          {brackets.map((br, i) =>
            br.height > 0 ? (
              <button
                key={i}
                type="button"
                className="bracket"
                style={{ top: br.top, height: br.height, animationDelay: reduceMotion ? undefined : `${i * 80}ms` }}
                onClick={() => showPassage(i)}
                aria-label={`Passage ${i + 1}: words ${fmtInt(passages[i].ws + 1)} to ${fmtInt(passages[i].we)}, flagged as AI-written`}
              >
                {passages.length > 1 && (
                  <span className="bracket-num" aria-hidden="true">
                    {i + 1}
                  </span>
                )}
              </button>
            ) : null,
          )}
        </div>
      </section>

      <aside className="margin" aria-label="Margin notes">
        <MarginFacts result={result} />
        {passages.length > 0 && (
          <ol className="queries" aria-label="Flagged passages">
            {passages.map((p, i) => (
              <li key={i} className="query">
                <button type="button" className="query-go" onClick={() => showPassage(i)}>
                  <span className="query-tag">
                    {passages.length > 1 && <>{i + 1} &middot; </>}Words {fmtInt(p.ws + 1)}&ndash;{fmtInt(p.we)}
                  </span>
                </button>
              </li>
            ))}
          </ol>
        )}
        <a className="text-link margin-link" href={DOWNLOAD_HREF}>
          Word by word in Squint for Mac
          <ArrowRightIcon size={16} />
        </a>
        <MarginGap result={result} />
      </aside>
    </div>
  );
}
