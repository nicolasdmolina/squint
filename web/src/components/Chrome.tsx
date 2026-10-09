import { Button } from '@astryxdesign/core/Button';
import { SegmentedControl, SegmentedControlItem } from '@astryxdesign/core/SegmentedControl';
import type { ReactNode } from 'react';
import { notes } from '../copy';
import { hrefFor, type Route, type ThemePref } from '../lib/hooks';
import type { Status } from '../types';
import { CardIcon, LensIcon, LockIcon, Mark, MoonIcon, SunIcon, SystemIcon, TargetIcon } from './Icons';

const NAV: { route: Route; label: string; short: string; icon: ReactNode }[] = [
  { route: 'check', label: 'Check text', short: 'Check', icon: <LensIcon size={18} /> },
  { route: 'accuracy', label: 'Accuracy', short: 'Accuracy', icon: <TargetIcon size={18} /> },
  { route: 'how', label: 'How it works', short: 'How it works', icon: <CardIcon size={18} /> },
];

export function TopBar({
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
  return (
    <header className="bar">
      <div className="bar-inner">
        <a className="brand" href="#/" aria-label="Squint, check text">
          <Mark size={28} />
          <span className="brand-name">Squint</span>
        </a>
        {unlocked && (
          <nav className="nav nav-top" aria-label="Sections">
            {NAV.map(item => (
              <a key={item.route} href={hrefFor(item.route)} className="nav-link" aria-current={route === item.route ? 'page' : undefined}>
                {item.label}
              </a>
            ))}
          </nav>
        )}
        <div className="bar-end">
          <SegmentedControl label="Colour theme" value={pref} onChange={v => onPref(v as ThemePref)} size="sm" className="theme-switch">
            <SegmentedControlItem value="system" label="Match system" isLabelHidden icon={<SystemIcon size={16} />} />
            <SegmentedControlItem value="light" label="Light" isLabelHidden icon={<SunIcon size={16} />} />
            <SegmentedControlItem value="dark" label="Dark" isLabelHidden icon={<MoonIcon size={16} />} />
          </SegmentedControl>
          {canLock && (
            <Button label="Lock" variant="ghost" size="sm" icon={<LockIcon size={16} />} className="lock-button" onClick={onLock} />
          )}
        </div>
      </div>
    </header>
  );
}

/** Phones get their own navigation: a pill of three routes in the thumb zone. */
export function BottomNav({ route }: { route: Route }) {
  return (
    <nav className="nav-bottom" aria-label="Sections">
      {NAV.map(item => (
        <a key={item.route} href={hrefFor(item.route)} className="nav-tab" aria-current={route === item.route ? 'page' : undefined}>
          {item.icon}
          <span>{item.short}</span>
        </a>
      ))}
    </nav>
  );
}

export function Footer({ status }: { status: Status | null }) {
  return (
    <footer className="footer">
      <p>{notes.privacy}</p>
      {status && (
        <p className="footer-models">
          Binoculars on {status.model_pair.observer} and {status.model_pair.performer}
        </p>
      )}
    </footer>
  );
}
