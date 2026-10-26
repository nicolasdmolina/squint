import { hrefFor, useMedia, type Route, type ThemePref } from '../lib/hooks';
import { LockIcon, MoonIcon, SunIcon } from './Icons';

const NAV: { route: Route; label: string }[] = [
  { route: 'check', label: 'Check' },
  { route: 'accuracy', label: 'Accuracy' },
  { route: 'how', label: 'How it works' },
];

/** The blue-pencil rail: wordmark, the three routes as underline tabs, theme and lock. */
export function Rail({
  route,
  unlocked,
  pref,
  onPref,
  canLock,
  onLock,
}: {
  route: Route;
  unlocked: boolean;
  pref: ThemePref;
  onPref: (p: ThemePref) => void;
  canLock: boolean;
  onLock: () => void;
}) {
  const systemDark = useMedia('(prefers-color-scheme: dark)');
  const dark = pref === 'dark' || (pref === 'system' && systemDark);
  // One button: it flips whatever is showing now. Going back to the system's choice clears the preference.
  const flip = () => {
    const next = dark ? 'light' : 'dark';
    onPref((next === 'dark') === systemDark ? 'system' : next);
  };
  return (
    <header className="rail">
      <div className="rail-inner">
        <a className="wordmark" href="#/" aria-label="Squint, check writing">
          Squint
        </a>
        {unlocked && <Tabs route={route} />}
        <div className="rail-end">
          <button type="button" className="rail-button" onClick={flip} aria-label={dark ? 'Switch to light theme' : 'Switch to dark theme'}>
            {dark ? <SunIcon size={18} /> : <MoonIcon size={18} />}
          </button>
          {canLock && (
            <button type="button" className="rail-button has-label" onClick={onLock}>
              <LockIcon size={16} />
              <span>Lock</span>
            </button>
          )}
        </div>
      </div>
      {unlocked && (
        <div className="rail-row">
          <Tabs route={route} />
        </div>
      )}
    </header>
  );
}

function Tabs({ route }: { route: Route }) {
  return (
    <nav className="tabs" aria-label="Sections">
      {NAV.map(item => (
        <a key={item.route} href={hrefFor(item.route)} className="tab" aria-current={route === item.route ? 'page' : undefined}>
          {item.label}
        </a>
      ))}
    </nav>
  );
}
