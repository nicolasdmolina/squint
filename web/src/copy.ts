// Squint's microcopy in one place, so the same thing is always called the same thing.
// Terms: a "check" is one run; "AI-like" = more predictable than expected; "human-like" =
// more surprising than expected; "score" = the raw Binoculars number; "cutoff" = a threshold;
// "passage" = a 150-word window; "AI-written share" = verdict.ai_percent.

import type { Band, Status } from './types';
import { fmtInt, fmtWait, plural } from './lib/format';
import { ApiError } from './api';

/** Squint for Mac, on the public landing page. The public site serves this app at /app/ and the landing at /. */
export const DOWNLOAD_HREF = '/#download';

export const LIMITS_FALLBACK: Status['limits'] = { min_words: 20, percent_min_words: 150, max_words: 2500, checks_per_hour: 30 };

export type Guide = { tone: 'idle' | 'short' | 'partial' | 'full' | 'over' | 'evidence'; text: string };

/** clfMin: the trained detector's minimum (verdicts start there), or null when it is off. */
export function lengthGuide(n: number, limits: Status['limits'], calibrated: boolean, clfMin: number | null = null, preview = false): Guide {
  const { min_words: min, percent_min_words: pct, max_words: max } = limits;
  if (n === 0) return { tone: 'idle', text: `Paste or type at least ${min} words.` };
  if (n < min) return { tone: 'short', text: `${min - n} more ${plural(min - n, 'word')} to get a verdict.` };
  if (n > max) {
    return { tone: 'over', text: `${fmtInt(n - max)} ${plural(n - max, 'word')} over the ${fmtInt(max)}-word limit. Trim it, or check it in parts.` };
  }
  if (clfMin != null && n < clfMin) {
    if (preview) return { tone: 'partial', text: `Add ${clfMin - n} more ${plural(clfMin - n, 'word')} for a verdict.` };
    return { tone: 'partial', text: `You'll get the evidence word by word. Add ${clfMin - n} more ${plural(clfMin - n, 'word')} for a verdict.` };
  }
  if (!calibrated && clfMin == null) return { tone: 'evidence', text: "You'll get the word-by-word evidence. Verdicts wait until Squint is tuned." };
  if (n < pct) {
    return { tone: 'partial', text: `You'll get a rough verdict. Add ${pct - n} more ${plural(pct - n, 'word')} for the AI-written share.` };
  }
  if (preview) return { tone: 'full', text: "You'll get a verdict, the AI-written share and the passages behind it." };
  return { tone: 'full', text: "You'll get the full reading: a verdict, the AI-written share and the evidence word by word." };
}

/** One plain sentence under the verdict. minWords is the trained detector's minimum; preview has no word marks. */
export function bandLine(band: Band, minWords = 50, preview = false): string {
  switch (band) {
    case 'likely_ai':
      return 'Reads like ChatGPT or Claude wrote it. Look at the marked passages before you say anything to the writer.';
    case 'likely_human':
      return 'Reads like a person wrote it. Squint still misses some AI writing, so this doesn’t prove it.';
    case 'uncertain':
      return 'Squint won’t call this one either way.';
    case 'uncalibrated':
      return preview ? 'Squint isn’t tuned yet, so there’s no verdict.' : 'Squint isn’t tuned yet, so there’s no verdict. The word marks still work.';
    case 'too_short':
      return preview ? `Squint needs ${minWords} words for a verdict.` : `Squint needs ${minWords} words for a verdict. The word marks still work.`;
  }
}

export const stage = {
  queue: { name: 'Queue', pending: 'Waiting for a turn', done: 'Done' },
  warmup: {
    name: 'Warm-up',
    pending: 'Only if the models are asleep',
    active: 'Waking the models, about half a minute',
    done: 'Done',
    skipped: 'Already awake',
  },
  scoring: {
    name: 'Reading',
    pending: 'Every word, both models',
    slow: 'Slower than usual. Still going.',
  },
};

/** The same stages on the preview server, which runs the classifier alone. */
export const stagePreview = {
  warmup: { pending: 'Only if the classifier is asleep', active: 'Loading the classifier' },
  scoring: { pending: 'The whole text, in passages' },
};

export const queueLine = (ahead: number) =>
  ahead > 0 ? `${ahead} ${plural(ahead, 'check')} ahead of yours` : 'You’re next';

export type UiError = { title: string; body: string; retry?: boolean; code: string; link?: { href: string; label: string } };

const runIt = { href: DOWNLOAD_HREF, label: 'Run Squint on your own Mac' };

/** Every failure as: what happened, why, and what to do next. `preview` is the public site (contract v1.3). */
export function describeError(e: unknown, limits: Status['limits'] = LIMITS_FALLBACK, preview = false): UiError {
  const err = e instanceof ApiError ? e : new ApiError(0, 'unknown', String(e));
  const wait = err.retryAfter ? fmtWait(err.retryAfter) : null;
  switch (err.code) {
    case 'offline':
      return {
        code: err.code,
        title: 'Squint is offline.',
        body: 'The Mac mini it runs on isn’t answering right now. Try again later. Your text is still here.',
        retry: true,
        link: runIt,
      };
    case 'too_short':
      return { code: err.code, title: 'Too short to check.', body: `Squint needs at least ${limits.min_words} words to say anything useful. Add a little more text.` };
    case 'too_long':
      return {
        code: err.code,
        title: 'Too long for one check.',
        body: `The limit ${preview ? 'here ' : ''}is ${fmtInt(limits.max_words)} words. Trim it, or check it in parts.`,
        link: preview ? { href: DOWNLOAD_HREF, label: 'Squint for Mac takes 2,500' } : undefined,
      };
    case 'rate_limited':
      return {
        code: err.code,
        title: 'Checks are paused for now.',
        body: `You've used this hour's ${limits.checks_per_hour} checks. ${wait ? `Try again in ${wait}.` : 'Try again a little later.'} Your text is still here.`,
        link: preview ? runIt : undefined,
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
      return {
        code: err.code,
        title: 'Squint is busy.',
        body: 'The line of checks is full right now. Try again in a minute. Your text is still here.',
        retry: true,
        link: preview ? runIt : undefined,
      };
    case 'model_unavailable':
      return preview
        ? { code: err.code, title: 'The classifier wouldn’t start.', body: 'Squint couldn’t load it. Try again in a minute.', retry: true, link: runIt }
        : { code: err.code, title: 'The models wouldn’t start.', body: 'Squint couldn’t load its language models. Try again in a minute. If it keeps happening, the server needs a restart.', retry: true };
    case 'invalid_request':
      return { code: err.code, title: 'Squint didn’t understand that request.', body: 'Something about the request was off. Try again, and if it keeps happening, reload the page.', retry: true };
    case 'network':
      return { code: err.code, title: 'Lost touch with Squint.', body: 'The server didn’t answer. Check your connection and try again. Your text is still here.', retry: true };
    default:
      return { code: err.code, title: 'The check didn’t finish.', body: 'Something went wrong on the server. Try again. Your text is still here.', retry: true };
  }
}

export const notes = {
  stored: 'Nothing is saved. This result is gone after 10 minutes.',
  privacy: 'Nothing you paste is stored. Squint runs on a private machine and forgets each result after 10 minutes.',
};

/** The known blind spot, said wherever a reading is shown. Source: calibration/classifier.json
 * (held-out texts of 50+ words, 18 Oct 2026 run). */
export const gap = {
  title: 'Squint still misses some Claude writing.',
  body: 'On texts of 50 words or more it caught 744 of 747 ChatGPT samples but 674 of 731 Claude samples, so “Likely human” doesn’t clear a text. Gemini and edited AI text haven’t been tested.',
  short: 'In testing it caught 744 of 747 ChatGPT samples but 674 of 731 Claude samples, so “Likely human” doesn’t clear a text.',
  shortUntuned: 'In testing it caught 744 of 747 ChatGPT samples but 674 of 731 Claude samples, so marks that look human-like don’t clear a text either.',
  margin: 'Short Claude writing slips through about 1 in 10.',
};

/** The same, for a server without the trained detector (Binoculars alone). Source: calibration/report.json (8 Oct 2026). */
export const gapBinoculars = {
  title: 'Squint misses most writing from current AI models.',
  body: 'In testing it caught none of 288 ChatGPT samples and about 1 in 9 Claude samples, so “Likely human” doesn’t clear a text. Gemini hasn’t been tested.',
  short: 'In testing it caught none of 288 ChatGPT samples and about 1 in 9 Claude samples, so “Likely human” doesn’t clear a text.',
  shortUntuned: 'In testing it caught none of 288 ChatGPT samples and about 1 in 9 Claude samples, so marks that look human-like don’t clear a text either.',
  margin: 'Most ChatGPT writing slips through.',
};
