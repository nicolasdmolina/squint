import { queueLine, stage, stagePreview } from '../copy';
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

/** Honest progress: each stage is one row that restyles in place as the job moves, and stays lit until the next lands. */
export function StageRows({ p, preview = false }: { p: Progress; preview?: boolean }) {
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
      text:
        warm === 'active'
          ? preview
            ? stagePreview.warmup.active
            : stage.warmup.active
          : warm === 'done'
            ? stage.warmup.done
            : warm === 'skipped'
              ? stage.warmup.skipped
              : preview
                ? stagePreview.warmup.pending
                : stage.warmup.pending,
      time: warm === 'active' ? secs(p.warmStart) : warm === 'done' ? secs(p.warmStart, p.scoreStart) : null,
    },
    {
      key: 'score',
      state: score,
      name: stage.scoring.name,
      text:
        score === 'active'
          ? `Reading ${words(p.words)}${preview ? '' : ' with both models'}.${(secs(p.scoreStart) ?? 0) >= SLOW_S ? ` ${stage.scoring.slow}` : ''}`
          : preview
            ? stagePreview.scoring.pending
            : stage.scoring.pending,
      time: score === 'active' ? secs(p.scoreStart) : null,
    },
  ];
  const current = rows.find(r => r.state === 'active');

  return (
    <div className="stages" id="check-progress">
      <ol className="stage-list" aria-label="Check progress">
        {rows.map(r => (
          <li key={r.key} className="stage" data-state={r.state}>
            <StageMark state={r.state} />
            <span className="stage-name">{r.name}</span>
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
  if (state === 'done') return <CheckIcon size={16} className="stage-mark is-done" />;
  return (
    <svg className={`stage-mark is-${state}`} width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      {state === 'active' ? (
        <>
          <circle cx="8" cy="8" r="6" className="ring-track" />
          <path d="M8 2a6 6 0 0 1 6 6" className="ring-arc" />
        </>
      ) : state === 'skipped' ? (
        <path d="M4 8h8" />
      ) : (
        <circle cx="8" cy="8" r="2.5" />
      )}
    </svg>
  );
}
