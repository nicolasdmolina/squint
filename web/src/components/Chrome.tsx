import { Button } from '@astryxdesign/core/Button';
import { SegmentedControl, SegmentedControlItem } from '@astryxdesign/core/SegmentedControl';
import { notes } from '../copy';
import { hrefFor, type Route, type ThemePref } from '../lib/hooks';
import type { Status } from '../types';
import { LockIcon, Mark, MoonIcon, SunIcon, SystemIcon } from './Icons';

const NAV: { route: Route; label: string }[] = [
  { route: 'check', label: 'Check text' },
  { route: 'accuracy', label: 'How accurate is this?' },
  { route: 'how', label: 'How it works' },
];

export function Nameplate({
  route,
  status,
  unlocked,
  pref,
  onPref,
}: {
  route: Route;
  status: Status | null;
  unlocked: boolean;
  pref: ThemePref;
  onPref: (p: ThemePref) => void;
}) {
  return (
    <header className="nameplate">
      <div className="nameplate-row">
        <a className="brand" href="#/" aria-label="Squint, check text">
          <Mark />
          <span className="brand-name">Squint</span>
        </a>
        {unlocked && status && <ModelPlate status={status} />}
        <div className="nameplate-end">
          <SegmentedControl label="Colour theme" value={pref} onChange={v => onPref(v as ThemePref)} size="sm" className="theme-switch">
            <SegmentedControlItem value="system" label="Match system" isLabelHidden icon={<SystemIcon size={16} />} />
            <SegmentedControlItem value="light" label="Light" isLabelHidden icon={<SunIcon size={16} />} />
            <SegmentedControlItem value="dark" label="Dark" isLabelHidden icon={<MoonIcon size={16} />} />
          </SegmentedControl>
        </div>
      </div>
      {unlocked && (
        <nav className="tabs" aria-label="Sections">
          {NAV.map(item => (
            <a key={item.route} href={hrefFor(item.route)} className="tab" aria-current={route === item.route ? 'page' : undefined}>
              {item.label}
            </a>
          ))}
        </nav>
      )}
    </header>
  );
}

function ModelPlate({ status }: { status: Status }) {
  const pair = status.model_pair.observer.replace(/\s*\(.*\)$/, '');
  return (
    <p className="plate">
      <span className="plate-cell">
        <span className="plate-key">Method</span> Binoculars
      </span>
      <span className="plate-cell">
        <span className="plate-key">Models</span> {pair} pair
      </span>
      <span className="plate-cell">
        <span className="plate-key">Tuned</span> {status.calibration.ready ? status.calibration.version ?? 'yes' : 'not yet'}
      </span>
    </p>
  );
}

export function Footer({ status, canLock, onLock }: { status: Status | null; canLock: boolean; onLock: () => void }) {
  return (
    <footer className="footer">
      <p className="footer-note">{notes.privacy}</p>
      {status && (
        <p className="footer-meta">
          {status.model_pair.observer} and {status.model_pair.performer}
        </p>
      )}
      {canLock && <Button label="Lock Squint" variant="ghost" size="sm" icon={<LockIcon size={16} />} onClick={onLock} />}
    </footer>
  );
}
