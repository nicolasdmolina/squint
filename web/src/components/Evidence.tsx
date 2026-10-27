import { Button } from '@astryxdesign/core/Button';
import { SegmentedControl, SegmentedControlItem } from '@astryxdesign/core/SegmentedControl';
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent, type ReactNode } from 'react';
import { fmtInt } from '../lib/format';
import { useMedia } from '../lib/hooks';
import { flaggedPassages } from '../lib/passages';
import { buildWords, leanShares, stopAt, type Word } from '../lib/words';
import type { Result } from '../types';
import { HeatText } from './HeatText';
import { ArrowLeftIcon, ArrowRightIcon, CloseIcon } from './Icons';
import { MarginFacts, MarginGap } from './Readout';
import { WordDetails } from './WordDetails';

/** Whole percentages for the glance line; the extremes say so rather than rounding to 0% or 100%. */
const fmtShare = (x: number) =>
  x <= 0 ? '0%' : x >= 1 ? '100%' : x < 0.005 ? 'under 1%' : x > 0.995 ? 'over 99%' : `${Math.round(x * 100)}%`;

const TIP_ID = 'word-tip';

/** The bottom edge of the sticky top bar: nothing should hide under it. */
const barBottom = () => document.querySelector('.rail')?.getBoundingClientRect().bottom ?? 0;

/** The result as a marked proof: the text with its pencil marks and margin brackets, the word lens, and the margin notes. */
export function Evidence({ result, text, head }: { result: Result; text: string; head: ReactNode }) {
  const { words, stops } = useMemo(() => buildWords(result, text), [result, text]);
  const [view, setView] = useState<'smooth' | 'raw'>('smooth');
  const smooth = view === 'smooth';
  const sheetMode = useMedia('(max-width: 760px), (pointer: coarse)');
  const reduceMotion = useMedia('(prefers-reduced-motion: reduce)');

  const [active, setActive] = useState<number | null>(null);
  const [tipOpen, setTipOpen] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [focusIdx, setFocusIdx] = useState(0);
  const [settled, setSettled] = useState(0);
  const [tipPos, setTipPos] = useState<{ left: number; top: number; above: boolean } | null>(null);

  const printRef = useRef<HTMLDivElement>(null);
  const sheetRef = useRef<HTMLDivElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const hideTimer = useRef(0);
  const els = useRef<HTMLElement[]>([]);

  // index the word elements once per render of the text
  useLayoutEffect(() => {
    els.current = Array.from(printRef.current?.querySelectorAll<HTMLElement>('.w[data-n]') ?? []);
  }, [words, view]);

  // roving tabindex, current-word mark and tooltip wiring, applied straight to the DOM
  useLayoutEffect(() => {
    const list = els.current;
    list.forEach(el => {
      el.tabIndex = -1;
      el.removeAttribute('aria-describedby');
      el.removeAttribute('data-current');
    });
    const f = list[focusIdx];
    if (f) f.tabIndex = 0;
    if (active != null && list[active]) {
      list[active].dataset.current = 'true';
      if (tipOpen && !sheetMode) list[active].setAttribute('aria-describedby', TIP_ID);
      if (sheetOpen && sheetMode) list[active].setAttribute('aria-describedby', `${TIP_ID}-sheet`);
    }
  }, [active, focusIdx, tipOpen, sheetOpen, sheetMode, view, words]);

  // place the desktop tooltip next to the active word, flipping above when there is no room
  useLayoutEffect(() => {
    if (!tipOpen || sheetMode || active == null) return setTipPos(null);
    const el = els.current[active];
    const box = printRef.current;
    const tip = tipRef.current;
    if (!el || !box || !tip) return;
    const r = el.getBoundingClientRect();
    const b = box.getBoundingClientRect();
    const tw = tip.offsetWidth;
    const th = tip.offsetHeight;
    const dockBottom = barBottom();
    const vh = window.innerHeight;
    const vw = document.documentElement.clientWidth;
    const fitsBelow = r.bottom + 8 + th + 8 <= vh;
    const fitsAbove = r.top - 8 - th - 8 >= dockBottom;
    if (fitsBelow || !fitsAbove) {
      // Neither side has room for the whole inspector: stand it beside the word instead, held inside
      // the viewport, so nothing it says is pushed off screen where hovering can't reach it.
      const roomRight = vw - r.right - 16;
      const roomLeft = r.left - 16;
      if (!fitsBelow && Math.max(roomRight, roomLeft) >= tw + 12) {
        const x = roomRight >= tw + 12 ? r.right + 12 : r.left - 12 - tw;
        const y = Math.max(dockBottom + 8, Math.min(r.top + r.height / 2 - th / 2, vh - th - 8));
        setTipPos({ left: x - b.left, top: y - b.top, above: false });
        return;
      }
    }
    const above = !fitsBelow && fitsAbove;
    const left = Math.max(0, Math.min(r.left - b.left + r.width / 2 - tw / 2, b.width - tw));
    const top = above ? r.top - b.top - th - 8 : r.bottom - b.top + 8;
    setTipPos({ left, top, above });
  }, [active, tipOpen, sheetMode, view, settled]);

  // re-place the inspector once scrolling settles (arrow keys scroll smoothly to the next word)
  useEffect(() => {
    if (!tipOpen || sheetMode) return;
    let t = 0;
    const onScroll = () => {
      window.clearTimeout(t);
      t = window.setTimeout(() => setSettled(k => k + 1), 120);
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll);
    return () => {
      window.clearTimeout(t);
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onScroll);
    };
  }, [tipOpen, sheetMode]);

  const indexFromEvent = (e: { target: EventTarget }) => {
    const el = (e.target as HTMLElement).closest?.('.w[data-n]') as HTMLElement | null;
    return el ? Number(el.dataset.n) : null;
  };

  const show = useCallback(
    (n: number) => {
      window.clearTimeout(hideTimer.current);
      setActive(n);
      if (!sheetMode) setTipOpen(true);
    },
    [sheetMode],
  );

  const scheduleHide = () => {
    window.clearTimeout(hideTimer.current);
    hideTimer.current = window.setTimeout(() => {
      const focused = document.activeElement as HTMLElement | null;
      if (focused?.closest?.('.w[data-n]') || tipRef.current?.matches(':hover')) return;
      setTipOpen(false);
    }, 160);
  };

  const scrollToWord = (n: number) => {
    const el = els.current[n];
    if (!el) return;
    const r = el.getBoundingClientRect();
    const topEdge = (barBottom()) + 24;
    // on phones the details sheet covers the bottom of the screen; it may not have rendered yet
    const sheetH = sheetMode ? (sheetRef.current?.offsetHeight ?? window.innerHeight * 0.48) : 0;
    const bottomEdge = window.innerHeight - sheetH - 24;
    if (r.top < topEdge || r.bottom > bottomEdge) {
      // centre the word in the strip of page left between the dock and the sheet
      const target = (topEdge + Math.max(topEdge, bottomEdge)) / 2;
      window.scrollBy({ top: r.top + r.height / 2 - target, behavior: reduceMotion ? 'auto' : 'smooth' });
    }
  };

  const goTo = (n: number, opts: { focus?: boolean } = {}) => {
    const k = Math.max(0, Math.min(stops.length - 1, n));
    setFocusIdx(k);
    show(k);
    if (opts.focus) els.current[k]?.focus({ preventScroll: true });
    scrollToWord(k);
  };

  const sentenceStart = (from: number, dir: 1 | -1) => {
    const s = stops[from].sentence;
    if (dir === 1) {
      const i = stops.findIndex((w, j) => j > from && w.sentence !== s);
      return i < 0 ? stops.length - 1 : i;
    }
    const startOfThis = stops.findIndex(w => w.sentence === s);
    if (startOfThis < from) return startOfThis;
    const prevSentence = stops[Math.max(0, startOfThis - 1)].sentence;
    return stops.findIndex(w => w.sentence === prevSentence);
  };

  const onTextKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const n = indexFromEvent(e);
    if (n == null) return;
    let to: number | null = null;
    if (e.key === 'ArrowRight') to = n + 1;
    else if (e.key === 'ArrowLeft') to = n - 1;
    else if (e.key === 'ArrowDown') to = sentenceStart(n, 1);
    else if (e.key === 'ArrowUp') to = sentenceStart(n, -1);
    else if (e.key === 'Home') to = 0;
    else if (e.key === 'End') to = stops.length - 1;
    else if (e.key === 'Escape') {
      setTipOpen(false);
      setSheetOpen(false);
      return;
    } else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      if (sheetMode) setSheetOpen(o => !o);
      else setTipOpen(o => !o);
      return;
    }
    if (to == null) return;
    e.preventDefault();
    goTo(to, { focus: true });
  };

  const onTextClick = (e: MouseEvent<HTMLDivElement>) => {
    const n = indexFromEvent(e);
    if (n == null) return;
    setFocusIdx(n);
    setActive(n);
    if (sheetMode) setSheetOpen(true);
    else setTipOpen(true);
  };

  // close the inspector when the pointer leaves the text and nothing in it has focus
  useEffect(() => () => window.clearTimeout(hideTimer.current), []);

  const shares = leanShares(stops, smooth);
  const current: Word | null = active != null ? stops[active] ?? null : null;

  // Flagged passages, merged where the overlapping windows touch: each becomes one margin bracket.
  const passages = useMemo(() => flaggedPassages(result.segments), [result.segments]);

  // Measure each passage's first and last line so its bracket spans exactly those lines.
  const [brackets, setBrackets] = useState<{ top: number; height: number }[]>([]);
  useLayoutEffect(() => {
    const box = printRef.current;
    if (!box || !passages.length) return setBrackets([]);
    const measure = () => {
      const b = box.getBoundingClientRect();
      setBrackets(
        passages.map(p => {
          const first = els.current[stopAt(stops, p.start)];
          let li = stopAt(stops, p.end);
          if (li > 0 && (stops[li]?.start ?? Infinity) >= p.end) li--;
          const last = els.current[li];
          if (!first || !last) return { top: 0, height: 0 };
          const r1 = first.getBoundingClientRect();
          const r2 = last.getBoundingClientRect();
          return { top: r1.top - b.top, height: r2.bottom - r1.top };
        }),
      );
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(box);
    void document.fonts?.ready.then(measure);
    return () => ro.disconnect();
  }, [passages, stops, view]);

  const showPassage = (i: number) => goTo(stopAt(stops, passages[i].start), { focus: true });

  return (
    <div className="proof is-result">
      <section className="galley" aria-labelledby="checker-title">
        {head}
        <div className="galley-tools">
          <SegmentedControl label="Marking" value={view} onChange={v => setView(v as 'smooth' | 'raw')} size="sm">
            <SegmentedControlItem value="smooth" label="Clear leans" />
            <SegmentedControlItem value="raw" label="Every word" />
          </SegmentedControl>
          <Legend />
        </div>
        <p className="sr-only" id="glance">
          {fmtShare(shares.ai)} of words lean AI-like and {fmtShare(shares.hu)} lean human-like.
        </p>
        <div
          className={`printout${smooth ? ' is-smooth' : ' is-raw'}`}
          ref={printRef}
          onMouseOver={e => {
            const n = indexFromEvent(e);
            if (n != null && !sheetMode) show(n);
          }}
          onMouseLeave={() => !sheetMode && scheduleHide()}
          onFocus={e => {
            const n = indexFromEvent(e);
            if (n != null) {
              setFocusIdx(n);
              show(n);
            }
          }}
          onBlur={() => !sheetMode && scheduleHide()}
          onKeyDown={onTextKey}
          onClick={onTextClick}
          aria-label="Your text, marked word by word"
          role="group"
          aria-describedby="glance printout-hint"
        >
          <p id="printout-hint" className="sr-only">
            Each word is a button that opens its details. Use the left and right arrow keys to move between words, up and down to
            jump between sentences, Home and End for the first and last word, and Escape to hide the details.
          </p>
          <HeatText text={text} result={result} words={words} smooth={smooth} />
          {brackets.map((br, i) =>
            br.height > 0 ? (
              <button
                key={i}
                type="button"
                className="bracket"
                style={{ top: br.top, height: br.height, animationDelay: reduceMotion ? undefined : `${i * 80}ms` }}
                onClick={() => showPassage(i)}
                aria-label={`Passage ${i + 1}: show words ${fmtInt(passages[i].ws + 1)} to ${fmtInt(passages[i].we)}, flagged as AI-like`}
              >
                {passages.length > 1 && <span className="bracket-num" aria-hidden="true">{i + 1}</span>}
              </button>
            ) : null,
          )}
          {!sheetMode && current && (
            <div
              ref={tipRef}
              id={TIP_ID}
              role="tooltip"
              className={`lens${tipOpen ? ' is-open' : ''}${tipPos?.above ? ' is-above' : ''}`}
              style={tipPos ? { left: tipPos.left, top: tipPos.top } : { left: 0, top: 0 }}
              onMouseEnter={() => window.clearTimeout(hideTimer.current)}
              onMouseLeave={scheduleHide}
            >
              <WordDetails word={current} result={result} smooth={smooth} />
            </div>
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
        <Reasons result={result} />
        <MarginGap result={result} />
      </aside>

      {sheetMode && current && sheetOpen && (
        <div className="sheet" role="region" aria-label="Word details" ref={sheetRef}>
          <div className="sheet-bar">
            <Button label="Previous word" icon={<ArrowLeftIcon size={16} />} isIconOnly variant="secondary" size="sm" onClick={() => goTo((active ?? 0) - 1)} />
            <Button label="Next word" icon={<ArrowRightIcon size={16} />} isIconOnly variant="secondary" size="sm" onClick={() => goTo((active ?? 0) + 1)} />
            <span className="sheet-count">
              Word {fmtInt(current.ord)} of {fmtInt(result.word_count)}
            </span>
            <Button
              label="Close word details"
              icon={<CloseIcon size={16} />}
              isIconOnly
              variant="ghost"
              size="sm"
              onClick={() => {
                setSheetOpen(false);
                els.current[active ?? 0]?.focus({ preventScroll: true });
              }}
            />
          </div>
          <div id={`${TIP_ID}-sheet`} className="sheet-body" role="group" tabIndex={0} aria-label={`Details for “${current.text}”`}>
            <WordDetails word={current} result={result} smooth={smooth} />
          </div>
        </div>
      )}
    </div>
  );
}

function Legend() {
  return (
    <ul className="legend" aria-label="Marks">
      <li>
        <span className="legend-sample" data-heat="ai3">word</span>
        AI-like
      </li>
      <li>
        <span className="legend-sample" data-heat="hu3">word</span>
        Human-like
      </li>
    </ul>
  );
}

function Reasons({ result }: { result: Result }) {
  if (!result.reasons.length) return null;
  return (
    <details className="why">
      <summary>What stood out</summary>
      <ul>
        {result.reasons.map((r, i) => (
          <li key={i} data-weight={r.weight}>
            {r.text}
          </li>
        ))}
      </ul>
    </details>
  );
}
