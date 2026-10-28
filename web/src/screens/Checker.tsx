import { Button } from '@astryxdesign/core/Button';
import { useEffect, useMemo, useRef, useState, type ChangeEvent, type DragEvent, type KeyboardEvent } from 'react';
import { api, ApiError } from '../api';
import { Evidence } from '../components/Evidence';
import { PreviewEvidence } from '../components/PreviewEvidence';
import { AlertIcon, CloseIcon, FileIcon, UploadIcon } from '../components/Icons';
import { Stops } from '../components/LengthMeter';
import { VerdictHead } from '../components/Readout';
import { StageRows, type Progress } from '../components/StageRows';
import { describeError, lengthGuide, LIMITS_FALLBACK, type UiError } from '../copy';
import { countWords, fmtInt, words } from '../lib/format';
import { reflowPdfText } from '../lib/reflow';
import { isPreviewResult, type Result, type Status } from '../types';

type Run =
  | { kind: 'idle' }
  | { kind: 'running'; progress: Progress }
  | { kind: 'done'; result: Result; text: string }
  | { kind: 'failed'; error: UiError; text: string };

const ACCEPT = '.docx,.pdf,.txt,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/pdf,text/plain';
const FILE_OK = /\.(docx|pdf|txt)$/i;
const MAX_FILE = 10 * 1024 * 1024;
const POLL_MS = 500;
const sleep = (ms: number) => new Promise(r => window.setTimeout(r, ms));

export function Checker({ status, onChecked }: { status: Status | null; onChecked: () => void }) {
  const limits = status?.limits ?? LIMITS_FALLBACK;
  const preview = status?.mode === 'preview';
  const publicSite = preview && !status?.app;
  const calibrated = status ? status.calibration.ready : true;
  const [text, setText] = useState('');
  const [run, setRun] = useState<Run>({ kind: 'idle' });
  const [inputError, setInputError] = useState<UiError | null>(null);
  const [upload, setUpload] = useState<{ busy: boolean; note: string | null; undo: string | null }>({ busy: false, note: null, undo: null });
  const [dropping, setDropping] = useState(false);
  const [announce, setAnnounce] = useState('');

  const areaRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const runToken = useRef(0);
  const extractAbort = useRef<AbortController | null>(null);
  const focusAfter = useRef<'area' | 'title' | null>(null);

  const n = useMemo(() => countWords(text), [text]);
  const clfMin = status?.classifier?.ready ? status.classifier.min_words : null;
  const guide = lengthGuide(n, limits, calibrated, clfMin, preview);
  const running = run.kind === 'running';

  // announce only when what you'd get changes, not on every keystroke
  const lastTone = useRef(guide.tone);
  useEffect(() => {
    if (guide.tone !== lastTone.current) {
      lastTone.current = guide.tone;
      setAnnounce(guide.tone === 'idle' ? '' : guide.text);
    }
  }, [guide.tone, guide.text]);

  useEffect(
    () => () => {
      runToken.current++;
      extractAbort.current?.abort();
    },
    [],
  );

  useEffect(() => {
    const target = focusAfter.current;
    if (!target) return;
    focusAfter.current = null;
    if (target === 'area') areaRef.current?.focus();
    else {
      titleRef.current?.focus({ preventScroll: true });
      titleRef.current?.scrollIntoView({ block: 'start' });
    }
  }, [run.kind]);

  // Keep progress and errors in view: on short screens they land below the composer.
  useEffect(() => {
    const id = inputError || run.kind === 'failed' ? 'sample-error' : run.kind === 'running' ? 'check-progress' : null;
    if (id) document.getElementById(id)?.scrollIntoView({ block: 'nearest' });
  }, [inputError, run.kind]);

  const edit = (value: string) => {
    if (running) return;
    setText(value);
    if (inputError) setInputError(null);
    if (upload.note) setUpload(u => ({ ...u, note: null, undo: null }));
    if (run.kind === 'failed') setRun({ kind: 'idle' });
  };

  const submit = async (source = text) => {
    if (running || upload.busy) return;
    const count = countWords(source);
    if (count < limits.min_words || count > limits.max_words) {
      setInputError(describeError(new ApiError(422, count < limits.min_words ? 'too_short' : 'too_long', ''), limits, publicSite));
      areaRef.current?.focus();
      return;
    }
    setInputError(null);
    const token = ++runToken.current;
    const live = () => token === runToken.current;
    const started = Date.now();
    let progress: Progress = { status: 'submitting', position: 0, words: count, started };
    setRun({ kind: 'running', progress });
    try {
      const job = await api.analyze(source);
      progress = { ...progress, status: 'queued', position: job.position };
      if (live()) setRun({ kind: 'running', progress });
      let misses = 0;
      while (live()) {
        await sleep(POLL_MS);
        if (!live()) return;
        let j;
        try {
          j = await api.job(job.job_id);
          misses = 0;
        } catch (e) {
          if (e instanceof ApiError && e.code === 'network' && ++misses <= 6) continue;
          throw e;
        }
        if (!live()) return;
        const now = Date.now();
        if (j.status === 'loading_model' && !progress.warmStart) progress = { ...progress, warmStart: now };
        if ((j.status === 'scoring' || j.status === 'done') && !progress.scoreStart) progress = { ...progress, scoreStart: now };
        if (j.status === 'error') throw new ApiError(500, j.error?.code ?? 'scoring_failed', j.error?.message ?? '');
        if (j.status === 'done' && j.result) {
          focusAfter.current = 'title';
          setRun({ kind: 'done', result: j.result, text: source });
          onChecked();
          return;
        }
        if (j.status !== progress.status || j.position !== progress.position) {
          progress = { ...progress, status: j.status, position: j.position };
          setRun({ kind: 'running', progress });
        }
      }
    } catch (e) {
      if (!live()) return;
      if (e instanceof ApiError && e.code === 'auth_required') {
        // the app locks itself; the text waits in the editor for the next unlock
        setRun({ kind: 'idle' });
        return;
      }
      if (e instanceof ApiError && (e.code === 'too_short' || e.code === 'too_long')) {
        setInputError(describeError(e, limits, publicSite));
        setRun({ kind: 'idle' });
        return;
      }
      setRun({ kind: 'failed', error: describeError(e, limits, publicSite), text: source });
      onChecked();
    }
  };

  const startOver = () => {
    runToken.current++;
    setText('');
    setInputError(null);
    setUpload({ busy: false, note: null, undo: null });
    focusAfter.current = 'area';
    setRun({ kind: 'idle' });
    window.scrollTo(0, 0);
  };

  const backToEdit = () => {
    runToken.current++;
    focusAfter.current = 'area';
    setRun({ kind: 'idle' });
    window.scrollTo(0, 0);
  };

  const takeFile = async (file: File | undefined) => {
    if (!file || running) return;
    if (!FILE_OK.test(file.name)) return setInputError(describeError(new ApiError(415, 'unsupported_file', ''), limits));
    if (file.size > MAX_FILE) return setInputError(describeError(new ApiError(413, 'file_too_large', ''), limits));
    extractAbort.current?.abort();
    const ctrl = new AbortController();
    extractAbort.current = ctrl;
    setInputError(null);
    setUpload(u => ({ ...u, busy: true }));
    try {
      const got = await api.extract(file, ctrl.signal);
      const previous = text;
      const isPdf = /\.pdf$/i.test(got.filename || file.name);
      const loaded = isPdf ? reflowPdfText(got.text) : got.text;
      const rejoined = loaded !== got.text;
      setText(loaded);
      if (run.kind === 'failed') setRun({ kind: 'idle' });
      setUpload({
        busy: false,
        note: `Loaded ${got.filename}: ${words(got.word_count)}.${rejoined ? ' We joined the PDF’s line breaks back into paragraphs, so give them a quick look before you check.' : ''}`,
        undo: previous.trim() && previous !== loaded ? previous : null,
      });
      areaRef.current?.focus();
    } catch (e) {
      if ((e as Error).name === 'AbortError') return;
      setUpload({ busy: false, note: null, undo: null });
      setInputError(describeError(e, limits, publicSite));
    }
  };

  const onFile = (e: ChangeEvent<HTMLInputElement>) => {
    void takeFile(e.target.files?.[0]);
    e.target.value = '';
  };

  const onDrag = (e: DragEvent<HTMLDivElement>, over: boolean) => {
    if (!Array.from(e.dataTransfer.types).includes('Files')) return;
    e.preventDefault();
    if (running) return;
    if (over !== dropping) setDropping(over);
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      void submit();
    }
  };

  if (run.kind === 'done') {
    const head = <VerdictHead result={run.result} percentMin={limits.percent_min_words} titleRef={titleRef} onAnother={startOver} onEdit={backToEdit} />;
    return (
      <div className="screen checker is-done">
        {isPreviewResult(run.result) ? (
          <PreviewEvidence result={run.result} text={run.text} head={head} download={publicSite} />
        ) : (
          <Evidence result={run.result} text={run.text} head={head} />
        )}
      </div>
    );
  }

  const error = inputError ?? (run.kind === 'failed' ? run.error : null);
  const state = running ? 'running' : dropping ? 'drop' : error ? 'error' : guide.tone;
  const restore = () => {
    setText(upload.undo ?? '');
    setUpload({ busy: false, note: 'Your earlier text is back.', undo: null });
    areaRef.current?.focus();
  };

  return (
    <div className="screen checker">
      <h1 id="checker-title" ref={titleRef} tabIndex={-1} className="sr-only">
        Check a piece of writing
      </h1>
      <div className="proof">
        <div
          className="galley composer"
          data-state={state}
          onDragEnter={e => onDrag(e, true)}
          onDragOver={e => onDrag(e, true)}
          onDragLeave={e => {
            if (!e.currentTarget.contains(e.relatedTarget as Node | null)) onDrag(e, false);
          }}
          onDrop={e => {
            if (!Array.from(e.dataTransfer.types).includes('Files')) return;
            e.preventDefault();
            setDropping(false);
            void takeFile(e.dataTransfer.files[0]);
          }}
        >
          <div className="galley-head">
            <label className="galley-label" htmlFor="sample">
              Your text
            </label>
            <span className="galley-count" aria-live="off">
              {fmtInt(n)} {n === 1 ? 'word' : 'words'}
            </span>
          </div>
          {/* A native textarea: Astryx's TextArea replaces id, aria-describedby, aria-invalid and readOnly with its own. */}
          <textarea
            ref={areaRef}
            id="sample"
            className="composer-input"
            value={text}
            onChange={e => edit(e.target.value)}
            onKeyDown={onKey}
            rows={14}
            placeholder="Paste or type the writing you want to check."
            spellCheck={false}
            readOnly={running}
            aria-describedby="sample-guide sample-error"
            aria-invalid={error && (error.code === 'too_short' || error.code === 'too_long') ? true : undefined}
          />
          {dropping && (
            <div className="composer-drop" aria-hidden="true">
              <FileIcon size={22} />
              Drop a .docx, .pdf or .txt file
            </div>
          )}
          {upload.note && (
            <div className="file-note">
              <FileIcon size={16} />
              <span className="file-note-text">{upload.note}</span>
              {upload.undo != null && (
                <button type="button" className="text-button" onClick={restore}>
                  Undo
                </button>
              )}
              <button
                type="button"
                className="icon-button"
                aria-label="Dismiss file note"
                onClick={() => setUpload(u => ({ ...u, note: null, undo: null }))}
              >
                <CloseIcon size={14} />
              </button>
            </div>
          )}
          <div id="sample-error" className="error-slot" role="alert">
            {error && (
              <div className="form-error">
                <AlertIcon size={18} />
                <p>
                  <strong>{error.title}</strong> {error.body}
                  {error.link && (
                    <>
                      {' '}
                      <a className="text-link" href={error.link.href}>
                        {error.link.label}
                      </a>
                    </>
                  )}
                </p>
              </div>
            )}
          </div>
          <div className="galley-foot">
            <Button
              label={upload.busy ? 'Reading the file' : 'Upload a file'}
              variant="ghost"
              size="sm"
              icon={<UploadIcon size={16} />}
              isLoading={upload.busy}
              isDisabled={running}
              onClick={() => fileRef.current?.click()}
            />
            <input ref={fileRef} type="file" accept={ACCEPT} className="sr-only" tabIndex={-1} aria-hidden="true" onChange={onFile} />
            <Button
              label={running ? 'Checking' : run.kind === 'failed' && run.error.retry ? 'Try again' : 'Check text'}
              variant="primary"
              isLoading={running}
              isDisabled={upload.busy || running}
              onClick={() => void submit()}
            />
          </div>
        </div>

        <aside className="margin" aria-label="Margin notes">
          {running ? <StageRows p={run.progress} preview={preview} /> : <Stops n={n} limits={limits} verdictAt={clfMin} preview={preview} />}
          <p id="sample-guide" className="sr-only">
            {guide.text}
          </p>
          {!running && !preview && <ModelNote status={status} />}
          {status && !calibrated && !status.classifier?.ready && (
            <div className="query">
              <p className="query-tag">Not tuned yet</p>
              <p className="query-text">You&rsquo;ll get the word marks, but no verdict or AI-written share.</p>
            </div>
          )}
          <p className="margin-quiet">
            {publicSite && `${limits.checks_per_hour} ${limits.checks_per_hour === 1 ? 'check' : 'checks'} an hour. `}Nothing you paste is stored.
          </p>
        </aside>
      </div>

      <p className="sr-only" role="status" aria-live="polite">
        {announce}
      </p>
    </div>
  );
}

/** What to expect from the machine right now, said before you wait rather than during. */
function ModelNote({ status }: { status: Status | null }) {
  if (!status) return null;
  const q = status.queue_length;
  const parts: string[] = [];
  if (status.model_state !== 'ready') parts.push('The models are asleep. The first check takes about 30 seconds longer.');
  if (q > 0) parts.push(`${q} ${q === 1 ? 'check is' : 'checks are'} in line.`);
  if (!parts.length) return null;
  return <p className="margin-note">{parts.join(' ')}</p>;
}
