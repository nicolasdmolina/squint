// Development-only mock of the Squint API (docs/api-contract.md), mounted as Vite middleware by
// `npm run dev:mock`. Not part of the production build: nothing in src/ imports this folder.
//
// Scenario switches for manual testing and screenshots:
//   GET  /__mock/state            -> current switches
//   POST /__mock/state {..}       -> merge switches (see `MockState`)
//   GET  /__mock/fixtures         -> the sample texts
// Mock password: "squint". For the public site: POST {"mode": "preview", "password_required": false};
// {"offline": true} answers every /api call the way the edge Worker does when the Mac mini is down.

import { readFileSync } from 'node:fs';
import type { IncomingMessage, ServerResponse } from 'node:http';
import type { Plugin } from 'vite';
import type { ClassifierAccuracy, Job, JobStatus, Result } from '../src/types.ts';
import { fixtures, fixtureText } from './fixtures.ts';
import { analyze, countWords, LIMITS, MOCK_ACCURACY, MODEL_PAIR, type MockClassifier } from './generate.ts';

type MockState = {
  /** contract v1.3: `preview` is the public site (classifier only, no word-level data, tighter limits) */
  mode: 'full' | 'preview';
  /** the Mac mini is unreachable: every /api call answers 503 offline, as the edge Worker does */
  offline: boolean;
  password_required: boolean;
  calibrated: boolean;
  /** the trained classifier is promoted (calibration/classifier.json); false = Binoculars only */
  classifier: boolean;
  /** false makes /api/accuracy answer 404 not_calibrated even when calibrated */
  accuracy: boolean;
  rate_limited: boolean;
  /** jobs waiting ahead of every new check */
  queue_ahead: number;
  /** the next check waits for the models to load */
  cold_start: boolean;
  /** the next check fails while scoring, with this job-level error code (true = scoring_failed) */
  job_error: boolean | 'scoring_failed' | 'model_unavailable';
  /** the queue is full: /api/analyze answers 503 busy */
  busy: boolean;
  /** freeze jobs in one phase for screenshots; null runs the normal timeline */
  hold: JobStatus | null;
  /** 1 = realistic timing; larger is faster */
  speed: number;
};

const DEFAULTS: MockState = {
  mode: 'full',
  offline: false,
  password_required: true,
  calibrated: true,
  classifier: true,
  accuracy: true,
  rate_limited: false,
  queue_ahead: 1,
  cold_start: true,
  job_error: false,
  busy: false,
  hold: null,
  speed: 1,
};

// the real promoted classifier's held-out numbers, so the accuracy copy can be checked against them
const CLASSIFIER: ClassifierAccuracy | null = (() => {
  try {
    const c = JSON.parse(readFileSync(new URL('../../calibration/classifier.json', import.meta.url), 'utf8'));
    return { version: c.version, model: c.model, min_words: c.min_words, held_out: c.held_out, by_length: c.by_length };
  } catch {
    return null;
  }
})();

// the same file's cutoffs, for mock verdicts
const CLASSIFIER_CFG: MockClassifier | null = (() => {
  try {
    const c = JSON.parse(readFileSync(new URL('../../calibration/classifier.json', import.meta.url), 'utf8'));
    return { version: c.version, min_words: c.min_words, ai_above: c.ai_above, human_below: c.human_below, by_length: c.by_length };
  } catch {
    return null;
  }
})();

const PREVIEW_LIMITS = { ...LIMITS, max_words: 500, checks_per_hour: 3 };

/** Contract v1.3 #2: a preview result keeps the shape with every word-level part emptied. */
function toPreview(r: Result): Result {
  return {
    ...r,
    token_count: null,
    model_pair: null,
    verdict: { ...r.verdict, detector: 'classifier', score: null, thresholds: null },
    reasons: r.reasons.filter(x => x.kind === 'detector'),
    stats: { top1_rate: null, top5_rate: null, mean_surprise: null, mean_expected_surprise: null, sentence_score_spread: null },
    tokens: [],
    sentences: [],
    paragraphs: [],
    segments: r.segments.map(x => ({ ...x, score: null })),
  };
}

const PASSWORD = 'squint';
const COOKIE = 'squint_mock_session';

type MockJob = {
  id: string;
  text: string;
  created: number;
  queueMs: number;
  loadMs: number;
  scoreMs: number;
  fail: false | 'scoring_failed' | 'model_unavailable';
  preview: boolean;
  result: Result | null;
};

export function squintMockApi(): Plugin {
  let state: MockState = { ...DEFAULTS };
  const sessions = new Set<string>();
  const jobs = new Map<string, MockJob>();
  let badLogins: number[] = [];
  let modelsWarm = false;

  const send = (res: ServerResponse, status: number, body?: unknown, headers: Record<string, string> = {}) => {
    res.statusCode = status;
    for (const [k, v] of Object.entries(headers)) res.setHeader(k, v);
    if (body === undefined) return res.end();
    res.setHeader('Content-Type', 'application/json');
    res.end(JSON.stringify(body));
  };
  // v1.1 #3: retry_after_s rides inside the error object and as a Retry-After header
  const fail = (res: ServerResponse, status: number, code: string, message: string, extra: { retry_after_s?: number } = {}) =>
    send(
      res,
      status,
      { error: { code, message, ...extra } },
      extra.retry_after_s != null ? { 'Retry-After': String(extra.retry_after_s) } : {},
    );

  const readBody = (req: IncomingMessage, limit = 11 * 1024 * 1024) =>
    new Promise<Buffer>((resolve, reject) => {
      const chunks: Buffer[] = [];
      let size = 0;
      req.on('data', (c: Buffer) => {
        size += c.length;
        if (size > limit) reject(Object.assign(new Error('too large'), { tooLarge: true }));
        else chunks.push(c);
      });
      req.on('end', () => resolve(Buffer.concat(chunks)));
      req.on('error', reject);
    });
  const readJson = async (req: IncomingMessage) => {
    try {
      return JSON.parse((await readBody(req)).toString('utf8') || '{}');
    } catch {
      return null;
    }
  };

  const sessionId = (req: IncomingMessage) => {
    const m = /(?:^|;\s*)squint_mock_session=([^;]+)/.exec(req.headers.cookie ?? '');
    return m?.[1];
  };
  const authed = (req: IncomingMessage) => !state.password_required || sessions.has(sessionId(req) ?? '');

  const jobView = (job: MockJob): Job => {
    const elapsed = (Date.now() - job.created) * state.speed;
    const base = { job_id: job.id, result: null, error: null };
    const phase = (): JobStatus => {
      if (state.hold) return state.hold;
      if (elapsed < job.queueMs) return 'queued';
      if (elapsed < job.queueMs + job.loadMs) return 'loading_model';
      if (elapsed < job.queueMs + job.loadMs + job.scoreMs) return 'scoring';
      return job.fail ? 'error' : 'done';
    };
    const status = phase();
    if (status === 'queued') {
      const left = state.hold ? job.queueMs : job.queueMs - elapsed;
      return { ...base, status, position: Math.max(1, Math.ceil(left / 1600)) };
    }
    if (status === 'loading_model' || status === 'scoring') {
      if (status === 'scoring') modelsWarm = true;
      return { ...base, status, position: 0 };
    }
    modelsWarm = true;
    if (status === 'error') {
      const error =
        job.fail === 'model_unavailable'
          ? { code: 'model_unavailable', message: 'The models could not be loaded.' }
          : { code: 'scoring_failed', message: 'Scoring failed on the server. Please try again.' };
      return { ...base, status, position: 0, error };
    }
    if (!job.result) {
      const full = analyze(job.text, {
        calibrated: state.calibrated,
        classifier: state.mode === 'preview' || state.classifier ? CLASSIFIER_CFG : null,
        timing: { queue: Math.round(job.queueMs), load: Math.round(job.loadMs), score: Math.round(job.scoreMs) },
      });
      job.result = job.preview ? toPreview(full) : full;
    }
    return { ...base, status: 'done', position: 0, result: job.result };
  };

  const handle = async (req: IncomingMessage, res: ServerResponse, next: () => void) => {
    const url = new URL(req.url ?? '/', 'http://mock');
    const path = url.pathname;
    const method = req.method ?? 'GET';

    if (path === '/__mock/state') {
      if (method === 'POST') {
        const body = await readJson(req);
        if (body?.reset) {
          state = { ...DEFAULTS };
          sessions.clear();
          jobs.clear();
          badLogins = [];
          modelsWarm = false;
        }
        const { reset: _reset, ...rest } = body ?? {};
        state = { ...state, ...rest };
        if (rest.cold_start === true) modelsWarm = false;
      }
      return send(res, 200, { ...state, models_warm: modelsWarm, sessions: sessions.size });
    }
    if (path === '/__mock/fixtures') {
      return send(res, 200, fixtures.map(f => ({ id: f.id, title: f.title, text: fixtureText(f), words: countWords(fixtureText(f)) })));
    }
    if (!path.startsWith('/api/')) return next();

    // small, realistic network delay
    await new Promise(r => setTimeout(r, 90));

    if (state.offline) return fail(res, 503, 'offline', 'Squint is offline right now. Try again later.');
    const preview = state.mode === 'preview';
    const limits = preview ? PREVIEW_LIMITS : LIMITS;

    if (path === '/api/session' && method === 'GET') {
      return send(res, 200, { authenticated: authed(req), password_required: state.password_required });
    }
    if (path === '/api/login' && method === 'POST') {
      const now = Date.now();
      badLogins = badLogins.filter(t => now - t < 60_000);
      if (badLogins.length >= 5) return fail(res, 429, 'rate_limited', 'Too many login attempts. Try again later.', { retry_after_s: 60 });
      const body = await readJson(req);
      if (body?.password !== PASSWORD) {
        badLogins.push(now);
        return fail(res, 401, 'bad_password', 'That password is not right.');
      }
      const id = Math.random().toString(36).slice(2);
      sessions.add(id);
      return send(res, 204, undefined, { 'Set-Cookie': `${COOKIE}=${id}; Path=/; HttpOnly; SameSite=Lax` });
    }
    if (path === '/api/logout' && method === 'POST') {
      sessions.delete(sessionId(req) ?? '');
      return send(res, 204, undefined, { 'Set-Cookie': `${COOKIE}=; Path=/; Max-Age=0` });
    }

    if (!authed(req)) return fail(res, 401, 'auth_required', 'Sign in with the password first.');

    if (path === '/api/status' && method === 'GET') {
      const active = [...jobs.values()].filter(j => jobView(j).status === 'queued').length;
      return send(res, 200, {
        mode: state.mode,
        model_state: modelsWarm ? 'ready' : [...jobs.values()].some(j => jobView(j).status === 'loading_model') ? 'loading' : 'unloaded',
        queue_length: active + state.queue_ahead,
        model_pair: preview ? null : MODEL_PAIR,
        calibration: { version: state.calibrated ? '2026-10-07' : null, ready: state.calibrated },
        classifier: state.classifier && CLASSIFIER
          ? { version: CLASSIFIER.version, ready: true, min_words: CLASSIFIER.min_words }
          : { version: null, ready: false, min_words: null },
        limits,
      });
    }

    if (path === '/api/extract' && method === 'POST') {
      let body: Buffer;
      try {
        body = await readBody(req);
      } catch (e) {
        if ((e as { tooLarge?: boolean }).tooLarge) return fail(res, 413, 'file_too_large', 'That file is over 10 MB.');
        throw e;
      }
      const ctype = req.headers['content-type'] ?? '';
      if (!ctype.toLowerCase().startsWith('multipart/form-data')) {
        return fail(res, 415, 'unsupported_file', "Upload the file as multipart/form-data in the field 'file'.");
      }
      const part = parseMultipartFile(body, ctype);
      if (!part) return fail(res, 400, 'invalid_request', "No file was found in the field 'file'.");
      if (part.data.length > 10 * 1024 * 1024) return fail(res, 413, 'file_too_large', 'That file is over 10 MB.');
      const ext = part.filename.toLowerCase().split('.').pop();
      let text: string;
      if (ext === 'txt') text = part.data.toString('utf8');
      else if (ext === 'docx') text = part.data.length < 64 ? '' : fixtureText(fixtures[2]);
      else if (ext === 'pdf') text = part.data.length < 64 ? '' : fixtureText(fixtures[1]);
      else return fail(res, 415, 'unsupported_file', 'Upload a .docx, .pdf or .txt file.');
      if (!text.trim()) return fail(res, 422, 'no_text_found', 'No readable text was found in that file.');
      return send(res, 200, { text, filename: part.filename, word_count: countWords(text) });
    }

    if (path === '/api/analyze' && method === 'POST') {
      if (state.rate_limited) {
        return fail(res, 429, 'rate_limited', `You've hit the limit of ${limits.checks_per_hour} checks an hour. Try again in 21 min.`, { retry_after_s: 1260 });
      }
      const body = await readJson(req);
      if (typeof body?.text !== 'string') return fail(res, 400, 'invalid_request', 'Send the text to check as {"text": "..."}.');
      const text: string = body.text;
      const words = countWords(text);
      if (words < limits.min_words) return fail(res, 422, 'too_short', `Paste at least ${limits.min_words} words. This text has ${words}.`);
      if (words > limits.max_words) return fail(res, 422, 'too_long', `Squint checks up to ${limits.max_words} words at a time. This text has ${words}.`);
      if (state.busy) return fail(res, 503, 'busy', 'Squint is busy right now. Try again in a minute.');
      const id = `j_${Math.random().toString(36).slice(2, 10)}`;
      const job: MockJob = {
        id,
        text,
        created: Date.now(),
        queueMs: state.queue_ahead * 1600,
        loadMs: state.cold_start && !modelsWarm ? (preview ? 1500 : 4200) : 0,
        scoreMs: preview ? 600 + words : 1200 + Math.min(2400, words * 4),
        fail: state.job_error === true ? 'scoring_failed' : state.job_error,
        preview,
        result: null,
      };
      jobs.set(id, job);
      if (jobs.size > 50) jobs.delete(jobs.keys().next().value!);
      return send(res, 202, { job_id: id, position: state.queue_ahead });
    }

    const jobMatch = /^\/api\/jobs\/([\w-]+)$/.exec(path);
    if (jobMatch && method === 'GET') {
      const job = jobs.get(jobMatch[1]);
      if (!job) return fail(res, 404, 'job_not_found', 'That check has expired or never existed.');
      return send(res, 200, jobView(job));
    }

    if (path === '/api/accuracy' && method === 'GET') {
      if (!state.calibrated || !state.accuracy) return fail(res, 404, 'not_calibrated', 'No calibration report yet.');
      return send(res, 200, state.classifier && CLASSIFIER ? { ...MOCK_ACCURACY, classifier: CLASSIFIER } : MOCK_ACCURACY);
    }

    return fail(res, 404, 'not_found', 'No such endpoint.');
  };

  return {
    name: 'squint-mock-api',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        handle(req, res, next).catch(err => {
          server.config.logger.error(`[squint-mock] ${String(err)}`);
          if (!res.headersSent) fail(res, 500, 'internal_error', 'The mock server hit an error.');
        });
      });
      server.config.logger.info('  squint mock API on /api (password: squint, switches at /__mock/state)');
    },
  };
}

function parseMultipartFile(body: Buffer, contentType: string): { filename: string; data: Buffer } | null {
  const m = /boundary=(?:"([^"]+)"|([^;]+))/.exec(contentType);
  if (!m) return null;
  const boundary = Buffer.from(`--${m[1] ?? m[2]}`);
  let pos = body.indexOf(boundary);
  while (pos >= 0) {
    const headerStart = pos + boundary.length + 2;
    const headerEnd = body.indexOf('\r\n\r\n', headerStart);
    if (headerEnd < 0) return null;
    const headers = body.subarray(headerStart, headerEnd).toString('utf8');
    const nextBoundary = body.indexOf(boundary, headerEnd + 4);
    if (nextBoundary < 0) return null;
    const nameMatch = /name="([^"]*)"/.exec(headers);
    const fileMatch = /filename="([^"]*)"/.exec(headers);
    if (nameMatch?.[1] === 'file' && fileMatch) {
      return { filename: fileMatch[1], data: body.subarray(headerEnd + 4, nextBoundary - 2) };
    }
    pos = nextBoundary;
  }
  return null;
}
