import { Button } from '@astryxdesign/core/Button';
import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '../api';
import { AlertIcon, ArrowRightIcon } from '../components/Icons';
import { gap, gapBinoculars } from '../copy';
import { fmtInt, fmtRate, oneIn } from '../lib/format';
import { hrefFor } from '../lib/hooks';
import type { Accuracy as AccuracyData, ClassifierAccuracy, GenCell, LengthBucket, Status } from '../types';

type Load = { kind: 'loading' } | { kind: 'ready'; data: AccuracyData } | { kind: 'untuned' } | { kind: 'failed' };

const LENGTHS: { key: LengthBucket; label: string }[] = [
  { key: '20-49', label: '20 to 49 words' },
  { key: '50-149', label: '50 to 149 words' },
  { key: '150+', label: '150 words or more' },
];

const SOURCE_NAMES: Record<string, string> = {
  chatgpt: 'ChatGPT',
  gpt4: 'GPT-4',
  claude: 'Claude',
  gemini: 'Gemini',
  llama: 'Llama',
  mistral: 'Mistral',
  deepseek: 'DeepSeek',
  qwen: 'Qwen',
};
const sourceName = (k: string) => SOURCE_NAMES[k.toLowerCase()] ?? k.replace(/[-_]+/g, ' ').replace(/^./, c => c.toUpperCase());

export function Accuracy({ status }: { status: Status | null }) {
  const [load, setLoad] = useState<Load>({ kind: 'loading' });
  const version = status?.calibration.version ?? null;

  const fetchIt = useCallback(() => {
    setLoad({ kind: 'loading' });
    api.accuracy().then(
      data => setLoad({ kind: 'ready', data }),
      e => setLoad(e instanceof ApiError && e.status === 404 ? { kind: 'untuned' } : { kind: 'failed' }),
    );
  }, []);
  useEffect(fetchIt, [fetchIt, version]);

  return (
    <div className="screen accuracy">
      <header className="screen-head">
        <h1>How accurate is this?</h1>
        <p className="lede">
          Squint is only worth listening to if it rarely flags people. Here is how it did on writing it had never seen, where the
          true source was known, and where it falls short.
        </p>
      </header>
      <KnownGap clf={status ? !!status.classifier?.ready : load.kind === 'ready' && !!load.data.classifier} />
      {load.kind === 'loading' && (
        <p className="quiet" role="status">
          Loading the test results&hellip;
        </p>
      )}
      {load.kind === 'failed' && (
        <div className="form-error" role="alert">
          <AlertIcon size={18} />
          <p>
            <strong>Couldn&rsquo;t load the test results.</strong> The server didn&rsquo;t answer. Try again in a moment.
          </p>
          <Button label="Try again" variant="secondary" size="sm" onClick={fetchIt} />
        </div>
      )}
      {load.kind === 'untuned' && <Untuned />}
      {load.kind === 'ready' && (load.data.classifier ? <ClassifierReport c={load.data.classifier} /> : <Report data={load.data} />)}
    </div>
  );
}

/** The gap is stated before any number, tuned or not. Source: docs/known-gaps.md. */
function KnownGap({ clf }: { clf: boolean }) {
  if (clf) {
    return (
      <section className="gap" aria-labelledby="gap-title">
        <h2 id="gap-title" className="gap-title">
          {gap.title}
        </h2>
        <p>
          In testing on texts of 50 words or more that it had never seen, Squint caught 599 of 607 ChatGPT samples and 478 of
          537 Claude samples. The Claude texts it missed were mostly short: under 150 words it caught about 85% of them.
          Gemini hasn&rsquo;t been tested, and neither has AI text that a person edited or ran through a paraphrasing tool.
        </p>
        <p className="gap-sub">
          A &ldquo;Likely human&rdquo; reading doesn&rsquo;t clear a text. Under 50 words Squint won&rsquo;t give a verdict
          at all.
        </p>
      </section>
    );
  }
  return (
    <section className="gap" aria-labelledby="gap-title">
      <h2 id="gap-title" className="gap-title">
        {gapBinoculars.title}
      </h2>
      <p>
        In testing on 8 October 2026, at the setting that keeps false flags under 1%, Squint caught none of 288 ChatGPT
        samples and 32 of 289 Claude samples. Writing from current models scores inside the range people write in, so this
        method alone can&rsquo;t separate it. Gemini hasn&rsquo;t been tested, because no samples could be generated.
      </p>
      <p className="gap-sub">
        A &ldquo;Likely human&rdquo; reading doesn&rsquo;t clear a text. A second, trained check for ChatGPT is planned before
        Squint is shared more widely.
      </p>
    </section>
  );
}

function Untuned() {
  return (
    <section className="untuned" aria-labelledby="untuned-title">
      <h2 id="untuned-title" className="section-title">
        Not tuned yet
      </h2>
      <p>
        Squint hasn&rsquo;t been tested yet, so there are no accuracy numbers to show. Tuning runs it on writing whose source is
        known: essays by students, including non-native English writers, and text from several AI models. The cutoffs are then
        set so that it very rarely calls a person&rsquo;s writing AI.
      </p>
      <p>
        Until then Squint still shows its word-by-word evidence, but it won&rsquo;t give a verdict or an AI-written share. A
        guess with no test behind it would be worse than no answer.
      </p>
      <a className="text-link" href={hrefFor('how')}>
        How Squint works
        <ArrowRightIcon size={16} />
      </a>
    </section>
  );
}

function Report({ data }: { data: AccuracyData }) {
  const ff = data.false_flag_rate;
  const cr = data.catch_rate;
  const lengthRows = (m: Partial<Record<LengthBucket, number>>) => LENGTHS.filter(l => m[l.key] != null).map(l => ({ label: l.label, v: m[l.key]! }));
  const sources = Object.entries(cr.by_source).sort((a, b) => b[1] - a[1]);
  const tested = new Set(sources.map(([k]) => k.toLowerCase()));
  const untested = ['chatgpt', 'claude', 'gemini'].filter(k => !tested.has(k));

  return (
    <>
      <p className="test-meta">
        Tested on {fmtInt(data.held_out.human)} human and {fmtInt(data.held_out.ai)} AI-written texts held back from tuning.
        Tuning version {data.version}.
      </p>

      <section className="acc-section" aria-labelledby="ff-title">
        <h2 id="ff-title" className="section-title">
          How often it wrongly flags people
        </h2>
        <p className="acc-lede">
          A false flag is human writing that Squint called <em className="term">Likely AI</em>. This is the number to watch.
        </p>
        <p className="headline">
          <span className="headline-num">{fmtRate(ff.overall)}</span>
          <span className="headline-cap">
            of human writing was flagged{ff.overall > 0 ? `, ${oneIn(ff.overall)}` : ''}.
          </span>
        </p>
        <RateRows
          caption="False flags by writer and length"
          rows={[
            { label: 'Non-native English writers', v: ff.non_native, note: 'Often flagged by other detectors. Squint is tuned on them on purpose.' },
            ...lengthRows(ff.by_length),
          ]}
          noun="human texts flagged"
        />
      </section>

      <section className="acc-section" aria-labelledby="catch-title">
        <h2 id="catch-title" className="section-title">
          How often it catches AI writing
        </h2>
        <p className="acc-lede">The share of AI-written texts that Squint called Likely AI. Missing some is the price of rarely flagging people.</p>
        <p className="headline">
          <span className="headline-num">{fmtRate(cr.overall)}</span>
          <span className="headline-cap">of AI writing was caught.</span>
        </p>
        <RateRows
          caption="Catch rate by model"
          rows={[
            ...sources.map(([k, v]) => ({
              label: sourceName(k),
              v,
              note: k.toLowerCase() === 'chatgpt' ? 'The known gap: most ChatGPT writing gets through.' : undefined,
            })),
            ...untested.map(k => ({ label: sourceName(k), v: null, note: 'Not tested yet.' })),
          ]}
          noun="caught"
        />
        <RateRows caption="Catch rate by length" rows={lengthRows(cr.by_length)} noun="caught" />
      </section>

      <section className="acc-section" aria-labelledby="unsure-title">
        <h2 id="unsure-title" className="section-title">
          How often it won&rsquo;t call it
        </h2>
        <p className="acc-lede">When a score lands where human and AI writing overlap, Squint says Uncertain instead of guessing.</p>
        <RateRows
          caption="Uncertain readings"
          rows={[
            { label: 'Human writing', v: data.uncertain_rate.human },
            { label: 'AI writing', v: data.uncertain_rate.ai },
          ]}
          noun="left uncertain"
        />
      </section>

      {data.notes.length > 0 && (
        <section className="acc-section" aria-labelledby="notes-title">
          <h2 id="notes-title" className="section-title">
            Notes from the test
          </h2>
          <ul className="acc-notes">
            {data.notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        </section>
      )}

      <p className="acc-foot">
        None of these numbers cover edited or paraphrased AI text, or very short pieces.{' '}
        <a className="text-link" href={`${hrefFor('how')}`}>
          Read about the blind spots
          <ArrowRightIcon size={16} />
        </a>
      </p>
    </>
  );
}

const GENS = ['chatgpt', 'claude'] as const;

/** Held-out results for the trained detector, which sets every verdict at min_words+ words. */
function ClassifierReport({ c }: { c: ClassifierAccuracy }) {
  const ff = c.held_out.false_flags;
  const nn = c.held_out.false_flags_non_native;
  const long = LENGTHS.filter(l => l.key !== '20-49');
  const cell = (b: LengthBucket, g: string) => c.by_length[b]?.[g] as GenCell | undefined;
  const pooled = (g: string, k: 'caught' | 'called_human') => {
    const cells = long.map(l => cell(l.key, g)).filter((x): x is GenCell => !!x);
    const n = cells.reduce((a, x) => a + x.n, 0);
    return n ? cells.reduce((a, x) => a + x[k] * x.n, 0) / n : null;
  };
  const lengthRows = (f: (b: LengthBucket) => number | null | undefined) =>
    long.map(l => ({ label: l.label, v: f(l.key) ?? null }));
  return (
    <>
      <p className="test-meta">
        Tested on {fmtInt(ff.n)} human texts and {fmtInt(GENS.reduce((a, g) => a + long.reduce((b, l) => b + (cell(l.key, g)?.n ?? 0), 0), 0))}{' '}
        AI-written texts of {c.min_words} words or more, all held back from training. Detector version {c.version}.
      </p>

      <section className="acc-section" aria-labelledby="ff-title">
        <h2 id="ff-title" className="section-title">
          How often it wrongly flags people
        </h2>
        <p className="acc-lede">
          A false flag is human writing that Squint called <em className="term">Likely AI</em>. This is the number to watch.
        </p>
        <p className="headline">
          <span className="headline-num">{fmtRate(ff.rate)}</span>
          <span className="headline-cap">
            of human writing was flagged: {fmtInt(ff.flagged)} of {fmtInt(ff.n)} texts.
          </span>
        </p>
        <RateRows
          caption="False flags by writer and length"
          rows={[
            {
              label: 'Non-native English writers',
              v: nn.rate,
              note: `${fmtInt(nn.flagged)} of ${fmtInt(nn.n)}. Often flagged by other detectors, so Squint is tested on them on purpose.`,
            },
            ...lengthRows(b => c.by_length[b]?.false_flag),
          ]}
          noun="human texts flagged"
        />
      </section>

      <section className="acc-section" aria-labelledby="catch-title">
        <h2 id="catch-title" className="section-title">
          How often it catches AI writing
        </h2>
        <p className="acc-lede">The share of AI-written texts that Squint called Likely AI. Missing some is the price of rarely flagging people.</p>
        <RateRows
          caption="Catch rate by model"
          rows={[
            ...GENS.map(g => ({
              label: sourceName(g),
              v: pooled(g, 'caught'),
              note: g === 'claude' ? 'The known gap: some Claude writing gets through, mostly in short texts.' : undefined,
            })),
            { label: sourceName('gemini'), v: null, note: 'Not tested yet.' },
          ]}
          noun="caught"
        />
        {GENS.map(g => (
          <RateRows key={g} caption={`${sourceName(g)} by length`} rows={lengthRows(b => cell(b, g)?.caught)} noun="caught" />
        ))}
      </section>

      <section className="acc-section" aria-labelledby="unsure-title">
        <h2 id="unsure-title" className="section-title">
          How often AI writing passes as human
        </h2>
        <p className="acc-lede">
          The share of AI-written texts that Squint called <em className="term">Likely human</em>. The rest of the misses landed
          in Uncertain.
        </p>
        <RateRows
          caption="Called likely human"
          rows={GENS.map(g => ({ label: sourceName(g), v: pooled(g, 'called_human') }))}
          noun="called human"
        />
      </section>

      <p className="acc-foot">
        None of these numbers cover edited or paraphrased AI text. Under {c.min_words} words Squint gives no verdict, because in
        testing it wrongly flagged {fmtRate(c.by_length['20-49']?.false_flag ?? 0)} of short human texts.{' '}
        <a className="text-link" href={`${hrefFor('how')}`}>
          Read about the blind spots
          <ArrowRightIcon size={16} />
        </a>
      </p>
    </>
  );
}

function reading(v: number, noun: string) {
  if (v <= 0) return 'None in the test set';
  if (v >= 0.995) return `All of them ${noun}`;
  const s = `${oneIn(v)} ${noun}`;
  return s.replace(/^./, c => c.toUpperCase());
}

/** Rows: the rate, a bar on a fixed 0 to 100% track, then the plain-language reading. */
function RateRows({
  caption,
  rows,
  noun,
}: {
  caption: string;
  rows: { label: string; v: number | null; note?: string }[];
  noun: string;
}) {
  if (!rows.length) return null;
  return (
    <figure className="rates">
      <figcaption className="rates-cap">{caption}</figcaption>
      <dl className="rate-list">
        {rows.map(r => (
          <div className="rate" key={r.label} data-untested={r.v == null || undefined}>
            <dt className="rate-label">{r.label}</dt>
            <dd className="rate-body">
              <span className="rate-value">{r.v == null ? 'Untested' : fmtRate(r.v)}</span>
              <span className="rate-bar" aria-hidden="true">
                {r.v != null && <span style={{ width: `${Math.min(100, r.v * 100)}%` }} data-zero={r.v === 0 || undefined} />}
              </span>
              <span className="rate-read">
                {r.v == null ? '' : reading(r.v, noun)}
                {r.note && <span className="rate-note">{r.v == null ? r.note : ` ${r.note}`}</span>}
              </span>
            </dd>
          </div>
        ))}
      </dl>
    </figure>
  );
}
