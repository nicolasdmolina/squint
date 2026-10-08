import { useEffect, useState, useSyncExternalStore } from 'react';

export type Route = 'check' | 'accuracy' | 'how';

const routeFromHash = (): Route => {
  const h = window.location.hash.replace(/^#\/?/, '');
  if (h.startsWith('accuracy')) return 'accuracy';
  if (h.startsWith('how-it-works')) return 'how';
  return 'check';
};

export const hrefFor = (r: Route) => (r === 'accuracy' ? '#/accuracy' : r === 'how' ? '#/how-it-works' : '#/');

/** Hash routes, so the Python server never needs an SPA fallback. */
export function useHashRoute(): Route {
  return useSyncExternalStore(
    cb => {
      window.addEventListener('hashchange', cb);
      return () => window.removeEventListener('hashchange', cb);
    },
    routeFromHash,
    () => 'check',
  );
}

export type ThemePref = 'system' | 'light' | 'dark';
const THEME_KEY = 'squint.theme';

function readPref(): ThemePref {
  try {
    const v = window.localStorage.getItem(THEME_KEY);
    return v === 'light' || v === 'dark' ? v : 'system';
  } catch {
    return 'system';
  }
}

export function useThemePref(): [ThemePref, (p: ThemePref) => void] {
  const [pref, setPref] = useState<ThemePref>(readPref);
  const update = (p: ThemePref) => {
    setPref(p);
    try {
      if (p === 'system') window.localStorage.removeItem(THEME_KEY);
      else window.localStorage.setItem(THEME_KEY, p);
    } catch {
      /* private mode: the choice lasts for this visit only */
    }
  };
  return [pref, update];
}

export function useMedia(query: string): boolean {
  return useSyncExternalStore(
    cb => {
      const m = window.matchMedia(query);
      m.addEventListener('change', cb);
      return () => m.removeEventListener('change', cb);
    },
    () => window.matchMedia(query).matches,
    () => false,
  );
}

/** Current time, ticking while `active`. */
export function useNow(active: boolean, every = 1000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const id = window.setInterval(() => setNow(Date.now()), every);
    return () => window.clearInterval(id);
  }, [active, every]);
  return now;
}
