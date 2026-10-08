import { useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';
import { fmtInt } from '../lib/format';
import { leanWord, type Word } from '../lib/words';
import type { Lean } from '../types';

export type StripMark = { at: number; lean: Lean };
export type StripSpan = { from: number; to: number };
export type ScrubHow = 'hover' | 'press' | 'key';

/**
 * The chart strip: the whole document's smoothed signal as one pen trace on chart paper.
 * Cobalt above the zero line is AI-like, amber below is human-like. Flagged passages are
 * bracketed above, sentence starts ticked below. Pointer or arrow keys scrub to a word.
 */
export function ChartStrip({
  stops,
  flagged,
  sentences,
  active,
  visible,
  compact,
  onScrub,
  onLeave,
}: {
  stops: Word[];
  flagged: StripSpan[];
  sentences: StripMark[];
  active: number | null;
  visible: [number, number] | null;
  compact: boolean;
  onScrub: (n: number, how: ScrubHow) => void;
  onLeave: () => void;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [hover, setHover] = useState<number | null>(null);
  const pressed = useRef(false);
  const frame = useRef(0);

  useLayoutEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width)));
    ro.observe(el);
    setWidth(Math.round(el.getBoundingClientRect().width));
    return () => ro.disconnect();
  }, []);
  useEffect(() => () => cancelAnimationFrame(frame.current), []);

  const n = stops.length;
  const H = compact ? 92 : 116;
  const top = 18;
  const bottom = H - 16;
  const mid = Math.round((top + bottom) / 2) + 0.5;
  const amp = (bottom - top) / 2 - 3;
  const padX = 0;
  const W = Math.max(1, width);
  const step = (W - padX * 2) / Math.max(1, n);
  const xAt = (i: number) => padX + (i + 0.5) * step;

  const { line, area } = useMemo(() => {
    if (!n || width < 2) return { line: '', area: '' };
    let l = '';
    for (let i = 0; i < n; i++) {
      const y = mid - stops[i].smooth * amp;
      l += `${i ? 'L' : 'M'}${xAt(i).toFixed(1)},${y.toFixed(1)}`;
    }
    const a = `M${xAt(0).toFixed(1)},${mid}${l.replace(/^M/, 'L')}L${xAt(n - 1).toFixed(1)},${mid}Z`;
    return { line: l, area: a };
  }, [stops, width, compact]); // eslint-disable-line react-hooks/exhaustive-deps

  const pick = (clientX: number) => {
    const r = wrap.current!.getBoundingClientRect();
    return Math.max(0, Math.min(n - 1, Math.floor(((clientX - r.left - padX) / (r.width - padX * 2)) * n)));
  };

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    pressed.current = true;
    e.currentTarget.setPointerCapture(e.pointerId);
    onScrub(pick(e.clientX), 'press');
  };
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const i = pick(e.clientX);
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(() => {
      if (pressed.current) onScrub(i, 'press');
      else if (e.pointerType === 'mouse') setHover(i);
    });
  };
  const endPress = () => {
    pressed.current = false;
  };
  const onPointerLeave = () => {
    if (pressed.current) return;
    setHover(null);
    onLeave();
  };

  const sentenceStarts = useMemo(() => sentences.map(s => s.at), [sentences]);
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const from = active ?? visible?.[0] ?? 0;
    let to: number | null = null;
    if (e.key === 'ArrowRight' || e.key === 'ArrowUp') to = from + 1;
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') to = from - 1;
    else if (e.key === 'PageDown') to = sentenceStarts.find(s => s > from) ?? n - 1;
    else if (e.key === 'PageUp') to = [...sentenceStarts].reverse().find(s => s < from) ?? 0;
    else if (e.key === 'Home') to = 0;
    else if (e.key === 'End') to = n - 1;
    if (to == null) return;
    e.preventDefault();
    onScrub(Math.max(0, Math.min(n - 1, to)), 'key');
  };

  const cursor = hover ?? active;
  const cursorWord = cursor != null ? stops[cursor] : null;
  const valueText = active != null ? `Word ${fmtInt(active + 1)} of ${fmtInt(n)}: ${stops[active].text}, ${leanWord(stops[active].smooth)}` : 'No word selected';

  // stack overlapping brackets on two rows
  const rows: number[] = [];
  const lastEnd = [-1, -1];
  for (const s of flagged) {
    const r = s.from > lastEnd[0] ? 0 : s.from > lastEnd[1] ? 1 : 0;
    rows.push(r);
    lastEnd[r] = s.to;
  }

  return (
    <div className="strip">
      <div className="strip-axis" aria-hidden="true">
        <span className="strip-axis-ai">AI-like</span>
        <span className="strip-axis-hu">Human-like</span>
      </div>
      <div
        ref={wrap}
        className="strip-plot"
        style={{ height: H }}
        role="slider"
        tabIndex={0}
        aria-label="Signal across the whole text"
        aria-valuemin={1}
        aria-valuemax={n}
        aria-valuenow={(active ?? 0) + 1}
        aria-valuetext={valueText}
        aria-describedby="strip-hint"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endPress}
        onPointerCancel={endPress}
        onPointerLeave={onPointerLeave}
        onKeyDown={onKeyDown}
      >
        {width > 1 && (
          <svg width={W} height={H} className="strip-svg" aria-hidden="true">
            <defs>
              <clipPath id="strip-above">
                <rect x="0" y="0" width={W} height={mid} />
              </clipPath>
              <clipPath id="strip-below">
                <rect x="0" y={mid} width={W} height={H - mid} />
              </clipPath>
            </defs>
            <g className="strip-grid">
              {Array.from({ length: Math.floor(W / 24) + 1 }, (_, i) => (
                <line key={i} x1={i * 24 + 0.5} x2={i * 24 + 0.5} y1={top} y2={bottom} className={i % 5 === 0 ? 'major' : undefined} />
              ))}
              {[-1, -0.5, 0.5, 1].map(k => (
                <line key={k} x1="0" x2={W} y1={Math.round(mid - k * amp) + 0.5} y2={Math.round(mid - k * amp) + 0.5} />
              ))}
            </g>
            {visible && (
              <rect
                className="strip-window"
                x={Math.max(0.5, xAt(visible[0]) - step / 2)}
                y={top - 2.5}
                width={Math.max(3, xAt(visible[1]) - xAt(visible[0]) + step)}
                height={bottom - top + 5}
              />
            )}
            <g className="strip-draw" key={n}>
              <path d={area} className="strip-fill-ai" clipPath="url(#strip-above)" />
              <path d={area} className="strip-fill-hu" clipPath="url(#strip-below)" />
              <line x1="0" x2={W} y1={mid} y2={mid} className="strip-zero" />
              <path d={line} className="strip-trace" pathLength={1} />
            </g>
            {flagged.map((s, i) => {
              const x1 = Math.round(xAt(s.from) - step / 2) + 0.5;
              const x2 = Math.round(xAt(s.to) + step / 2) - 0.5;
              const y = 3.5 + rows[i] * 6;
              return <path key={i} className="strip-bracket" d={`M${x1},${y + 5}V${y}H${x2}V${y + 5}`} />;
            })}
            {sentences.map((s, i) => {
              const x = Math.round(xAt(s.at) - step / 2) + 0.5;
              const base = H - 8;
              if (s.lean === 'ai') return <line key={i} className="tick tick-ai" x1={x} x2={x} y1={base} y2={base - 6} />;
              if (s.lean === 'human') return <line key={i} className="tick tick-hu" x1={x} x2={x} y1={base} y2={base + 6} />;
              return <circle key={i} className="tick tick-nu" cx={x} cy={base} r={1.5} />;
            })}
            {cursor != null && (
              <g className={`strip-cursor${hover != null && hover !== active ? ' is-hover' : ''}`}>
                <line x1={Math.round(xAt(cursor)) + 0.5} x2={Math.round(xAt(cursor)) + 0.5} y1={top - 4} y2={bottom + 4} />
                <rect x={Math.round(xAt(cursor)) - 3} y={mid - stops[cursor].smooth * amp - 3.5} width="7" height="7" />
              </g>
            )}
          </svg>
        )}
        {cursorWord && (
          <span
            className="strip-read"
            style={{ left: Math.min(Math.max(xAt(cursor!), 60), W - 60) }}
            aria-hidden="true"
          >
            {cursorWord.text} &middot; {leanWord(cursorWord.smooth)}
          </span>
        )}
      </div>
      <p id="strip-hint" className="sr-only">
        Left and right arrows move one word. Page Up and Page Down jump between sentences.
      </p>
    </div>
  );
}
