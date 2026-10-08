import { Button } from '@astryxdesign/core/Button';
import { SegmentedControl, SegmentedControlItem } from '@astryxdesign/core/SegmentedControl';
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent } from 'react';
import { fmtInt } from '../lib/format';
import { useMedia } from '../lib/hooks';
import { buildWords, leanShares, stopAt, type Word } from '../lib/words';
import type { Result } from '../types';
import { ChartStrip, type ScrubHow } from './ChartStrip';
import { HeatText } from './HeatText';
import { ArrowLeftIcon, ArrowRightIcon, CloseIcon } from './Icons';
import { WordDetails } from './WordDetails';

/** Whole percentages for the glance line; the extremes say so rather than rounding to 0% or 100%. */
const fmtShare = (x: number) =>
  x <= 0 ? '0%' : x >= 1 ? '100%' : x < 0.005 ? 'under 1%' : x > 0.995 ? 'over 99%' : `${Math.round(x * 100)}%`;

const TIP_ID = 'word-tip';

/** "Show me why": the chart strip, the reprinted text with its heat, and the word inspector. */
export function Evidence({ result, text }: { result: Result; text: string }) {
  const { words, stops } = useMemo(() => buildWords(result, text), [result, text]);
  const [view, setView] = useState<'smooth' | 'raw'>('smooth');
  const smooth = view === 'smooth';
  const sheetMode = useMedia('(max-width: 760px), (pointer: coarse)');
  const reduceMotion = useMedia('(prefers-reduced-motion: reduce)');

  const [active, setActive] = useState<number | null>(null);
  const [tipOpen, setTipOpen] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [focusIdx, setFocusIdx] = useState(0);
  const [visible, setVisible] = useState<[number, number] | null>(null);
  const [settled, setSettled] = useState(0);
  const [tipPos, setTipPos] = useState<{ left: number; top: number; above: boolean } | null>(null);

  const printRef = useRef<HTMLDivElement>(null);
  const sheetRef = useRef<HTMLDivElement>(null);
  const dockRef = useRef<HTMLDivElement>(null);
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
    const dockBottom = dockRef.current?.getBoundingClientRect().bottom ?? 0;
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

  // which words are on screen, for the strip's window
  useEffect(() => {
    let raf = 0;
    const measure = () => {
      raf = 0;
      const list = els.current;
      if (!list.length) return;
      const topEdge = dockRef.current?.getBoundingClientRect().bottom ?? 0;
      const bottomEdge = window.innerHeight;
      const first = bsearch(list, el => el.getBoundingClientRect().bottom >= topEdge);
      const last = bsearch(list, el => el.getBoundingClientRect().top > bottomEdge) - 1;
      if (first >= list.length || last < 0 || last < first) setVisible(null);
      else setVisible(v => (v && v[0] === first && v[1] === last ? v : [first, last]));
    };
    const schedule = () => {
      if (!raf) raf = requestAnimationFrame(measure);
    };
    schedule();
    window.addEventListener('scroll', schedule, { passive: true });
    window.addEventListener('resize', schedule);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('scroll', schedule);
      window.removeEventListener('resize', schedule);
    };
  }, [words, view]);

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
    const topEdge = (dockRef.current?.getBoundingClientRect().bottom ?? 0) + 24;
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

  const onScrub = (n: number, how: ScrubHow) => {
    setFocusIdx(n);
    setActive(n);
    if (!sheetMode) setTipOpen(how !== 'hover');
    scrollToWord(n);
  };

  // close the inspector when the pointer leaves the text and nothing in it has focus
  useEffect(() => () => window.clearTimeout(hideTimer.current), []);

  const shares = leanShares(stops, smooth);
  const flagged = useMemo(
    () =>
      result.segments
        .filter(s => s.flagged)
        .map(s => ({ from: stopAt(stops, s.start), to: Math.max(stopAt(stops, s.start), stopAt(stops, s.end - 1)) })),
    [result, stops],
  );
  const sentenceMarks = useMemo(
    () => result.sentences.map(s => ({ at: Math.min(stops.length - 1, stopAt(stops, s.start)), lean: s.lean })),
    [result, stops],
  );
  const current: Word | null = active != null ? stops[active] ?? null : null;

  return (
    <section className="evidence" aria-labelledby="why-title">
      <header className="evidence-head">
        <h2 id="why-title" className="section-title">
          Show me why
        </h2>
        <p className="evidence-lede">
          Every word is shaded by how predictable it was to the models. Blue with a solid underline means more predictable than
          expected, which is AI-like. Amber with a dotted underline means more surprising, which is human-like. Hover a word, or
          tab into the text and use the arrow keys, to see what the model guessed.
        </p>
      </header>

      <div className="evidence-tools">
        <SegmentedControl label="Shading" value={view} onChange={v => setView(v as 'smooth' | 'raw')} size="sm">
          <SegmentedControlItem value="smooth" label="Smoothed" />
          <SegmentedControlItem value="raw" label="Word by word" />
        </SegmentedControl>
        <Legend />
        <p className="glance">
          <strong>{fmtShare(shares.ai)}</strong> of words lean AI-like and <strong>{fmtShare(shares.hu)}</strong> lean
          human-like. The rest show no clear lean.
        </p>
      </div>

      {/* the key sits above the dock so the strip that stays on screen is only the strip */}
      <StripKey hasFlags={flagged.length > 0} />
      <div className="strip-dock" ref={dockRef}>
        <ChartStrip
          stops={stops}
          flagged={flagged}
          sentences={sentenceMarks}
          active={active}
          visible={visible}
          compact={sheetMode}
          onScrub={onScrub}
          onLeave={() => undefined}
        />
      </div>

      <div className="evidence-body">
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
          aria-label="Your text, shaded word by word"
          role="group"
          aria-describedby="printout-hint"
        >
          <p id="printout-hint" className="sr-only">
            Each word is a button. Use the left and right arrow keys to move between words, up and down to jump between sentences,
            and Escape to hide the details.
          </p>
          <HeatText text={text} result={result} words={words} smooth={smooth} />
          {!sheetMode && current && (
            <div
              ref={tipRef}
              id={TIP_ID}
              role="tooltip"
              className={`tip${tipOpen ? ' is-open' : ''}${tipPos?.above ? ' is-above' : ''}`}
              style={tipPos ? { left: tipPos.left, top: tipPos.top } : { left: 0, top: 0 }}
              onMouseEnter={() => window.clearTimeout(hideTimer.current)}
              onMouseLeave={scheduleHide}
            >
              <WordDetails word={current} result={result} smooth={smooth} />
            </div>
          )}
        </div>
        <div className="evidence-side">
          <Reasons result={result} />
          {result.segments.length > 0 && <Passages result={result} stops={stops} onShow={n => goTo(n, { focus: true })} />}
        </div>
      </div>

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
    </section>
  );
}

function bsearch<T>(list: T[], pred: (x: T) => boolean) {
  let lo = 0;
  let hi = list.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (pred(list[mid])) hi = mid;
    else lo = mid + 1;
  }
  return lo;
}

function Legend() {
  return (
    <ul className="legend" aria-label="Shading key">
      <li>
        <span className="legend-sample" data-heat="ai3">word</span>
        More predictable, AI-like
      </li>
      <li>
        <span className="legend-sample" data-heat="hu3">word</span>
        More surprising, human-like
      </li>
      <li>
        <span className="legend-sample" data-heat="nu0">word</span>
        No clear lean
      </li>
    </ul>
  );
}

function StripKey({ hasFlags }: { hasFlags: boolean }) {
  return (
    <p className="strip-key" aria-hidden="true">
      {hasFlags && (
        <span>
          <svg width="22" height="8" viewBox="0 0 22 8"><path d="M1 7.5V1.5H21V7.5" /></svg>
          Flagged passage
        </span>
      )}
      <span>
        <svg width="8" height="12" viewBox="0 0 8 12"><line className="tick-ai" x1="4" x2="4" y1="11" y2="3" /></svg>
        Sentence leans AI-like
      </span>
      <span>
        <svg width="8" height="12" viewBox="0 0 8 12"><line className="tick-hu" x1="4" x2="4" y1="1" y2="9" /></svg>
        Sentence leans human-like
      </span>
      <span>
        <svg width="16" height="10" viewBox="0 0 16 10"><rect className="strip-window" x="0.5" y="0.5" width="15" height="9" /></svg>
        On screen now
      </span>
    </p>
  );
}

const WEIGHT_LABEL = { strong: 'Strong signal', moderate: 'Moderate signal', weak: 'Weak signal' } as const;

function Reasons({ result }: { result: Result }) {
  if (!result.reasons.length) return null;
  return (
    <section className="reasons" aria-labelledby="reasons-title">
      <h3 id="reasons-title" className="side-title">
        What stood out
      </h3>
      <ul>
        {result.reasons.map((r, i) => (
          <li key={i} className="reason">
            <span className="weight" data-weight={r.weight} title={WEIGHT_LABEL[r.weight]}>
              <span />
              <span />
              <span />
              <span className="sr-only">{WEIGHT_LABEL[r.weight]}:</span>
            </span>
            <span className="reason-text">{r.text}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Passages({ result, stops, onShow }: { result: Result; stops: Word[]; onShow: (n: number) => void }) {
  const untuned = result.verdict.band === 'uncalibrated';
  return (
    <section className="passages" aria-labelledby="passages-title">
      <h3 id="passages-title" className="side-title">
        Passages
      </h3>
      <p className="side-note">Overlapping {result.segments[0].word_end - result.segments[0].word_start}-word stretches, each scored on its own.</p>
      <ol>
        {result.segments.map((s, i) => (
          <li key={i} className="passage" data-flagged={s.flagged || undefined}>
            <span className="passage-range">
              Words {fmtInt(s.word_start + 1)}&ndash;{fmtInt(s.word_end)}
            </span>
            <span className="passage-score">{s.score.toFixed(3)}</span>
            <span className="passage-state">{s.flagged ? 'Flagged as AI-like' : untuned ? 'No flags until tuned' : 'Not flagged'}</span>
            <button type="button" className="passage-go" onClick={() => onShow(stopAt(stops, s.start))}>
              Show<span className="sr-only"> words {fmtInt(s.word_start + 1)} to {fmtInt(s.word_end)} in the text</span>
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}
