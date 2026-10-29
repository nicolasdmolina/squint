import { Button } from '@astryxdesign/core/Button';
import { useState } from 'react';
import { PreviewEvidence } from '../components/PreviewEvidence';
import { verdictLine } from '../components/Readout';
import { DOWNLOAD_HREF } from '../copy';
import examples from '../examples.json';
import { words } from '../lib/format';
import type { Result } from '../types';

type Example = { label: string; source: string; text: string; result: Result };
const EXAMPLES = examples as unknown as Example[];

/**
 * Shown when every checking server is offline: real preview results for fixed texts, built by
 * web/examples/make.py, so the site still shows what Squint does.
 */
export function Examples({ onRetry }: { onRetry: () => void }) {
  const [at, setAt] = useState(0);
  const { text, result, source } = EXAMPLES[at];
  const v = result.verdict;
  const head = (
    <header className="verdict-head">
      <p className="verdict-meta">
        {source} &middot; {words(result.word_count)}
      </p>
      <h1 id="checker-title" tabIndex={-1} className="verdict" data-band={v.band}>
        {v.label}
      </h1>
      <p className="verdict-line">{verdictLine(result)}</p>
      <div className="verdict-actions" role="group" aria-label="Examples">
        {EXAMPLES.map((ex, i) => (
          <Button
            key={ex.label}
            label={ex.label}
            variant={i === at ? 'primary' : 'secondary'}
            aria-pressed={i === at}
            onClick={() => setAt(i)}
          />
        ))}
      </div>
    </header>
  );
  return (
    <div className="screen checker is-done is-examples">
      <div className="offline-note" role="status">
        <p>
          <b>Checking is offline right now.</b> These are Squint&rsquo;s real results on three texts.
        </p>
        <div className="boot-actions">
          <Button label="Try again" variant="secondary" onClick={onRetry} />
          <a className="text-link" href={DOWNLOAD_HREF}>
            Run Squint on your own Mac
          </a>
        </div>
      </div>
      <PreviewEvidence key={at} result={result} text={text} head={head} />
    </div>
  );
}
