// Squint's microcopy in one place, so the same thing is always called the same thing.
// Terms: a "check" is one run; "AI-like" = more predictable than expected; "human-like" =
// more surprising than expected; "score" = the raw Binoculars number; "cutoff" = a threshold;
// "passage" = a 150-word window; "AI-written share" = verdict.ai_percent.

import type { Band, Status } from './types';
import { fmtInt, fmtWait, plural } from './lib/format';
import { ApiError } from './api';

export const LIMITS_FALLBACK: Status['limits'] = { min_words: 20, percent_min_words: 150, max_words: 2500, checks_per_hour: 30 };

export type Guide = { tone: 'idle' | 'short' | 'partial' | 'full' | 'over' | 'evidence'; text: string };

/** clfMin: the trained detector's minimum (verdicts start there), or null when it is off. */
export function lengthGuide(n: number, limits: Status['limits'], calibrated: boolean, clfMin: number | null = null): Guide {
  const { min_words: min, percent_min_words: pct, max_words: max } = limits;
  if (n === 0) return { tone: 'idle', text: `Paste or type at least ${min} words.` };
  if (n < min) return { tone: 'short', text: `${min - n} more ${plural(min - n, 'word')} to get a verdict.` };
  if (n > max) {
    return { tone: 'over', text: `${fmtInt(n - max)} ${plural(n - max, 'word')} over the ${fmtInt(max)}-word limit. Trim it, or check it in parts.` };
  }
  if (clfMin != null && n < clfMin) {
    return { tone: 'partial', text: `You'll get the evidence word by word. Add ${clfMin - n} more ${plural(clfMin - n, 'word')} for a verdict.` };
  }
  if (!calibrated && clfMin == null) return { tone: 'evidence', text: "You'll get the word-by-word evidence. Verdicts wait until Squint is tuned." };
  if (n < pct) {
    return { tone: 'partial', text: `You'll get a rough verdict. Add ${pct - n} more ${plural(pct - n, 'word')} for the AI-written share.` };
  }
  return { tone: 'full', text: "You'll get the full reading: a verdict, the AI-written share and the evidence word by word." };
}

export const bandLine: Record<Band, string> = {
  likely_ai: 'Reads like AI writing. Worth a closer look, not an accusation.',
  likely_human: 'No sign of AI writing. That still doesn’t prove a person wrote it.',
  uncertain: 'Human and AI writing both land here. Look at the marks below rather than the label.',
  uncalibrated: 'Squint isn’t tuned yet, so it won’t give a verdict. The evidence below still holds.',
  too_short: 'There isn’t enough text for a verdict. The marks below still show which words read as AI-like.',
};

export const stage = {
  queue: { name: 'Queue', pending: 'Waiting for a turn', done: 'Your turn came up' },
  warmup: {
    name: 'Warm-up',
    pending: 'Only needed if the models are asleep',
    active: 'Warming up the models. The first check after a break takes about half a minute.',
    done: 'Models ready',
    skipped: 'Models were already warm',
  },
  scoring: {
    name: 'Scoring',
    pending: 'Both models read every word',
    slow: 'This is taking longer than usual. The machine may be busy with other work; your check is still going.',
  },
};

export const queueLine = (ahead: number) =>
  ahead > 0 ? `${ahead} ${plural(ahead, 'check')} ahead of yours` : 'You’re next';

export type UiError = { title: string; body: string; retry?: boolean; code: string };

/** Every failure as: what happened, why, and what to do next. */
export function describeError(e: unknown, limits: Status['limits'] = LIMITS_FALLBACK): UiError {
  const err = e instanceof ApiError ? e : new ApiError(0, 'unknown', String(e));
  const wait = err.retryAfter ? fmtWait(err.retryAfter) : null;
  switch (err.code) {
    case 'too_short':
      return { code: err.code, title: 'Too short to check.', body: `Squint needs at least ${limits.min_words} words to say anything useful. Add a little more text.` };
    case 'too_long':
      return { code: err.code, title: 'Too long for one check.', body: `The limit is ${fmtInt(limits.max_words)} words. Trim it, or check it in parts.` };
    case 'rate_limited':
      return {
        code: err.code,
        title: 'Checks are paused for now.',
        body: `You've used this hour's ${limits.checks_per_hour} checks. ${wait ? `Try again in ${wait}.` : 'Try again a little later.'} Your text is still here.`,
      };
    case 'auth_required':
      return { code: err.code, title: 'Squint locked itself.', body: 'Your session ended. Enter the password again and your text will be waiting.' };
    case 'unsupported_file':
      return { code: err.code, title: 'Squint can’t read that file type.', body: 'Upload a .docx, .pdf or .txt file, or paste the text instead.' };
    case 'file_too_large':
      return { code: err.code, title: 'That file is too big.', body: 'Files can be up to 10 MB. Paste the text instead, or upload a smaller file.' };
    case 'no_text_found':
      return { code: err.code, title: 'No text found in that file.', body: 'Scanned PDFs are often just pictures of pages. Paste the text instead.' };
    case 'job_not_found':
      return { code: err.code, title: 'That result has expired.', body: 'Results are kept for 10 minutes and never saved. Check the text again.', retry: true };
    case 'busy':
      return { code: err.code, title: 'Squint is busy.', body: 'The line of checks is full right now. Try again in a minute. Your text is still here.', retry: true };
    case 'model_unavailable':
      return { code: err.code, title: 'The models wouldn’t start.', body: 'Squint couldn’t load its language models. Try again in a minute. If it keeps happening, the server needs a restart.', retry: true };
    case 'invalid_request':
      return { code: err.code, title: 'Squint didn’t understand that request.', body: 'Something about the request was off. Try again, and if it keeps happening, reload the page.', retry: true };
    case 'network':
      return { code: err.code, title: 'Lost touch with Squint.', body: 'The server didn’t answer. Check your connection and try again. Your text is still here.', retry: true };
    default:
      return { code: err.code, title: 'The check didn’t finish.', body: 'Something went wrong on the server. Try again. Your text is still here.', retry: true };
  }
}

export const notes = {
  evidence: 'Evidence, not proof. Treat this as one clue among several, especially before saying anything to the writer.',
  stored: 'Nothing is saved. This result disappears after 10 minutes, or as soon as you check something else.',
  privacy: 'Nothing you paste is stored. Squint runs on a private machine and forgets each result after 10 minutes.',
};

/** The known blind spot, said wherever a reading is shown. Source: calibration/classifier.json
 * (held-out texts of 50+ words, 18 Oct 2026 run). */
export const gap = {
  title: 'Squint still misses some Claude writing.',
  body: 'On texts of 50 words or more it caught 744 of 747 ChatGPT samples but 674 of 731 Claude samples, so “Likely human” doesn’t clear a text. Gemini and edited AI text haven’t been tested.',
  short: 'In testing it caught 744 of 747 ChatGPT samples but 674 of 731 Claude samples, so “Likely human” doesn’t clear a text.',
  shortUntuned: 'In testing it caught 744 of 747 ChatGPT samples but 674 of 731 Claude samples, so marks that look human-like don’t clear a text either.',
};

/** The same, for a server without the trained detector (Binoculars alone). Source: calibration/report.json (8 Oct 2026). */
export const gapBinoculars = {
  title: 'Squint misses most writing from current AI models.',
  body: 'In testing it caught none of 288 ChatGPT samples and about 1 in 9 Claude samples, so “Likely human” doesn’t clear a text. Gemini hasn’t been tested.',
  short: 'In testing it caught none of 288 ChatGPT samples and about 1 in 9 Claude samples, so “Likely human” doesn’t clear a text.',
  shortUntuned: 'In testing it caught none of 288 ChatGPT samples and about 1 in 9 Claude samples, so marks that look human-like don’t clear a text either.',
};
