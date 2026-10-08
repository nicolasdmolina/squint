import { queueLine, stage } from '../copy';
import { useNow } from '../lib/hooks';
import { words } from '../lib/format';
import type { JobStatus } from '../types';
import { CheckIcon } from './Icons';

export type Progress = {
  status: JobStatus | 'submitting';
  position: number;
  words: number;
  started: number;
  warmStart?: number;
  scoreStart?: number;
};

/** After this long in scoring, say so: the machine may be busy with other work. */
const SLOW_S = 30;

type RowState = 'pending' | 'active' | 'done' | 'skipped';

/** Honest progress: each stage is one ruled row that restyles in place as the job moves. */
export function StageRows({ p }: { p: Progress }) {
  const now = useNow(true);
  const s = p.status;
  const queue: RowState = s === 'submitting' || s === 'queued' ? 'active' : 'done';
  const warm: RowState =
    s === 'loading_model' ? 'active' : s === 'scoring' || s === 'done' ? (p.warmStart ? 'done' : 'skipped') : 'pending';
  const score: RowState = s === 'scoring' ? 'active' : s === 'done' ? 'done' : 'pending';
  const secs = (from?: number, to?: number) => (from ? Math.max(0, Math.round(((to ?? now) - from) / 1000)) : null);

  const rows = [
    {
      key: 'queue',
      state: queue,
      name: stage.queue.name,
      text: queue === 'active' ? (s === 'submitting' ? 'Sending your text' : queueLine(p.position)) : stage.queue.done,
      time: queue === 'active' ? secs(p.started) : null,
    },
    {
      key: 'warm',
      state: warm,
      name: stage.warmup.name,
      text: warm === 'active' ? stage.warmup.active : warm === 'done' ? stage.warmup.done : warm === 'skipped' ? stage.warmup.skipped : stage.warmup.pending,
      time: warm === 'active' ? secs(p.warmStart) : warm === 'done' ? secs(p.warmStart, p.scoreStart) : null,
    },
    {
      key: 'score',
      state: score,
      name: stage.scoring.name,
      text:
        score === 'active'
          ? `Reading ${words(p.words)} with both models.${(secs(p.scoreStart) ?? 0) >= SLOW_S ? ` ${stage.scoring.slow}` : ''}`
          : stage.scoring.pending,
      time: score === 'active' ? secs(p.scoreStart) : null,
    },
  ];
  const current = rows.find(r => r.state === 'active');

  return (
    <div className="stages">
      <ol className="rows" aria-label="Check progress">
        {rows.map(r => (
          <li key={r.key} className="row stage" data-state={r.state}>
            <span className="row-label">
              <StageMark state={r.state} />
              {r.name}
            </span>
            <span className="stage-text">{r.text}</span>
            <span className="stage-time" aria-hidden="true">
              {r.time != null ? `${r.time}s` : ''}
            </span>
            <span className="sr-only">{r.state === 'active' ? '(in progress)' : r.state === 'done' ? '(done)' : r.state === 'skipped' ? '(skipped)' : '(waiting)'}</span>
          </li>
        ))}
      </ol>
      <p className="sr-only" role="status" aria-live="polite">
        {current ? `${current.name}: ${current.text}` : ''}
      </p>
    </div>
  );
}

function StageMark({ state }: { state: RowState }) {
  if (state === 'done') return <CheckIcon size={14} className="stage-mark is-done" />;
  if (state === 'active') {
    return (
      <svg className="stage-mark is-active" width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
        <path className="pen" d="M1 8 L4 5 L6.5 9 L9 4 L11 7.5 L13 6" fill="none" pathLength={1} />
      </svg>
    );
  }
  return (
    <svg className={`stage-mark is-${state}`} width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
      {state === 'skipped' ? <path d="M3 7h8" /> : <rect x="3.5" y="3.5" width="7" height="7" />}
    </svg>
  );
}
