const nf = new Intl.NumberFormat('en-US');

export const fmtInt = (n: number) => nf.format(n);

export const plural = (n: number, one: string, many = `${one}s`) => (n === 1 ? one : many);

export const words = (n: number) => `${fmtInt(n)} ${plural(n, 'word')}`;

/** Rates: 0.008 -> "0.8%", 0.83 -> "83%". */
export function fmtRate(x: number) {
  const p = x * 100;
  if (p === 0) return '0%';
  if (p < 10) return `${p.toFixed(1).replace(/\.0$/, '')}%`;
  return `${Math.round(p)}%`;
}

/** "about 1 in 125" style reading of a small rate. */
export function oneIn(x: number) {
  if (x <= 0) return 'none in the test set';
  if (x >= 0.5) return `about ${Math.round(x * 10)} in 10`;
  return `about 1 in ${fmtInt(nice(1 / x))}`;
}

/** Round to two significant figures for plain-language odds. */
export function nice(n: number) {
  if (n < 10) return Math.max(2, Math.round(n));
  const mag = 10 ** (Math.floor(Math.log10(n)) - 1);
  return Math.round(n / mag) * mag;
}

export function ordinal(n: number) {
  const s = ['th', 'st', 'nd', 'rd'];
  const v = n % 100;
  return `${fmtInt(n)}${s[(v - 20) % 10] || s[v] || s[0]}`;
}

/** A probability as plain odds: 0.42 -> "about 42%", 0.03 -> "about 1 in 33". */
export function odds(p: number) {
  if (p >= 0.95) return 'near certain';
  if (p >= 0.2) return `about ${Math.round(p * 100)}%`;
  return `about 1 in ${fmtInt(nice(1 / p))}`;
}

export const fmtP = (p: number) => (p >= 0.995 ? '>99%' : p < 0.01 ? '<1%' : `${Math.round(p * 100)}%`);

export function fmtWait(seconds: number) {
  if (seconds < 60) return `${Math.max(1, Math.round(seconds))} ${plural(Math.round(seconds), 'second')}`;
  const m = Math.ceil(seconds / 60);
  if (m < 60) return `${m} ${plural(m, 'minute')}`;
  const h = Math.floor(m / 60);
  const r = m % 60;
  return r ? `${h} h ${r} min` : `${h} ${plural(h, 'hour')}`;
}

/** Show a model token: keep inner text, make whitespace visible in words. */
export function showToken(t: string) {
  if (/^\s*\n\s*$/.test(t)) return t.includes('\n\n') ? '(new paragraph)' : '(line break)';
  if (!t.trim()) return '(space)';
  return t.trim();
}

export const countWords = (text: string) => (text.match(/\S+/g) ?? []).length;
