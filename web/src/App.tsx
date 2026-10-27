import { Button } from '@astryxdesign/core/Button';
import { Theme } from '@astryxdesign/core/theme';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError, onAuthRequired } from './api';
import { Rail } from './components/Chrome';
import { useHashRoute, useThemePref } from './lib/hooks';
import { Accuracy } from './screens/Accuracy';
import { Checker } from './screens/Checker';
import { HowItWorks } from './screens/HowItWorks';
import { Login } from './screens/Login';
import { DOWNLOAD_HREF } from './copy';
import { squintTheme } from './theme';
import type { Session, Status } from './types';

const TITLES = { check: 'Squint', accuracy: 'Accuracy · Squint', how: 'How it works · Squint' };

export function App() {
  const route = useHashRoute();
  const [pref, setPref] = useThemePref();
  const [session, setSession] = useState<Session | null>(null);
  /** why the first call failed: the contract's error code, or null while it hasn't */
  const [bootFailed, setBootFailed] = useState<string | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [lockNote, setLockNote] = useState<string | null>(null);
  const [everUnlocked, setEverUnlocked] = useState(false);
  const mainRef = useRef<HTMLElement>(null);
  const firstRoute = useRef(true);

  const loadSession = useCallback(() => {
    setBootFailed(null);
    api.session().then(setSession, e => setBootFailed(e instanceof ApiError ? e.code : 'unknown'));
  }, []);
  useEffect(loadSession, [loadSession]);

  useEffect(
    () =>
      onAuthRequired(() => {
        setSession(s => (s ? { ...s, authenticated: false } : s));
        setLockNote('Your session ended. Enter the password again and your text will be waiting.');
      }),
    [],
  );

  const unlocked = !!session && (!session.password_required || session.authenticated);
  useEffect(() => {
    if (unlocked) setEverUnlocked(true);
  }, [unlocked]);

  const refreshStatus = useCallback(() => {
    api.status().then(setStatus, () => undefined);
  }, []);
  useEffect(() => {
    if (unlocked) refreshStatus();
  }, [unlocked, refreshStatus]);

  useEffect(() => {
    document.title = unlocked ? TITLES[route] : 'Squint';
    if (firstRoute.current) {
      firstRoute.current = false;
      return;
    }
    window.scrollTo(0, 0);
    mainRef.current?.focus({ preventScroll: true });
  }, [route, unlocked]);

  const lock = async () => {
    try {
      await api.logout();
    } finally {
      setLockNote(null);
      setSession(s => (s ? { ...s, authenticated: false } : s));
    }
  };

  return (
    <Theme theme={squintTheme} mode={pref}>
      <div className={`app${unlocked ? ' is-unlocked' : ''}`}>
        <button type="button" className="skip" onClick={() => mainRef.current?.focus()}>
          Skip to content
        </button>
        <Rail
          route={route}
          unlocked={unlocked}
          pref={pref}
          onPref={setPref}
          canLock={!!session?.password_required && unlocked}
          onLock={lock}
        />
        <main id="main" ref={mainRef} tabIndex={-1} className="main">
          {!session && (bootFailed ? <BootFailed code={bootFailed} onRetry={loadSession} /> : <Booting />)}
          {session && !unlocked && (
            <Login
              note={lockNote}
              onUnlocked={() => {
                setLockNote(null);
                setSession({ ...session, authenticated: true });
              }}
            />
          )}
          {everUnlocked && (
            <div hidden={!unlocked || route !== 'check'}>
              <Checker status={status} onChecked={refreshStatus} />
            </div>
          )}
          {unlocked && route === 'accuracy' && <Accuracy status={status} />}
          {unlocked && route === 'how' && <HowItWorks status={status} />}
        </main>
      </div>
    </Theme>
  );
}

function Booting() {
  return (
    <p className="boot" role="status">
      Opening Squint&hellip;
    </p>
  );
}

function BootFailed({ code, onRetry }: { code: string; onRetry: () => void }) {
  // `offline` comes from the public site's edge when the Mac mini behind it is unreachable.
  if (code === 'offline') {
    return (
      <div className="boot" role="alert">
        <p className="boot-title">Squint is offline.</p>
        <p>The Mac mini it runs on isn&rsquo;t answering right now. Try again later.</p>
        <div className="boot-actions">
          <Button label="Try again" variant="secondary" onClick={onRetry} />
          <a className="text-link" href={DOWNLOAD_HREF}>
            Run Squint on your own Mac
          </a>
        </div>
      </div>
    );
  }
  return (
    <div className="boot" role="alert">
      <p className="boot-title">Squint isn&rsquo;t answering.</p>
      <p>The server may be restarting. Wait a moment, then try again.</p>
      <Button label="Try again" variant="secondary" onClick={onRetry} />
    </div>
  );
}
