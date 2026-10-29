import type { Accuracy, ApiErrorBody, Job, Session, Status } from './types';

/** Any failed call. `code` is the contract's snake_case code, or `network` when the server is unreachable. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryAfter?: number;
  constructor(status: number, code: string, message: string, retryAfter?: number) {
    super(message);
    this.status = status;
    this.code = code;
    this.retryAfter = retryAfter;
  }
}

type Listener = () => void;
const authListeners = new Set<Listener>();
/** Called whenever any request answers 401 auth_required (session expired or never unlocked). */
export function onAuthRequired(fn: Listener) {
  authListeners.add(fn);
  return () => void authListeners.delete(fn);
}

async function request<T>(path: string, init: RequestInit = {}, signal?: AbortSignal): Promise<T> {
  const headers = new Headers(init.headers);
  if (typeof init.body === 'string') headers.set('Content-Type', 'application/json');
  headers.set('Accept', 'application/json');
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { credentials: 'same-origin', ...init, headers, signal });
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e;
    throw new ApiError(0, 'network', 'Could not reach the server.');
  }
  if (res.status === 204) return undefined as T;
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  if (!res.ok) {
    const err = (body as ApiErrorBody | null)?.error;
    const header = Number(res.headers.get('Retry-After'));
    const retry = err?.retry_after_s ?? (Number.isFinite(header) && header > 0 ? header : undefined);
    const error = new ApiError(res.status, err?.code ?? `http_${res.status}`, err?.message ?? res.statusText, retry);
    if (error.code === 'auth_required') authListeners.forEach(fn => fn());
    throw error;
  }
  return body as T;
}

export type Extracted = { text: string; filename: string; word_count: number };

export const api = {
  session: () => request<Session>('/session'),
  login: (password: string) => request<void>('/login', { method: 'POST', body: JSON.stringify({ password }) }),
  logout: () => request<void>('/logout', { method: 'POST' }),
  status: () => request<Status>('/status'),
  extract: (file: File, signal?: AbortSignal) => {
    const form = new FormData();
    form.append('file', file);
    return request<Extracted>('/extract', { method: 'POST', body: form }, signal);
  },
  /** A queued job to poll, or (in preview) the finished job itself. */
  analyze: (text: string) =>
    request<{ job_id: string; position: number } | Job>('/analyze', { method: 'POST', body: JSON.stringify({ text }) }),
  job: (id: string, signal?: AbortSignal) => request<Job>(`/jobs/${encodeURIComponent(id)}`, {}, signal),
  accuracy: () => request<Accuracy>('/accuracy'),
};
