import { Button } from '@astryxdesign/core/Button';
import { TextInput } from '@astryxdesign/core/TextInput';
import { useLayoutEffect, useRef, useState, type FormEvent } from 'react';
import { api, ApiError } from '../api';
import { AlertIcon, Mark } from '../components/Icons';
import { fmtWait } from '../lib/format';

export function Login({ note, onUnlocked }: { note: string | null; onUnlocked: () => void }) {
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Astryx's TextInput writes its own aria-describedby, so the error link is set on the element.
  useLayoutEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    if (error) el.setAttribute('aria-describedby', 'gate-error');
    else el.removeAttribute('aria-describedby');
  }, [error]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!password) {
      setError('Type the password first.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.login(password);
      onUnlocked();
    } catch (err) {
      const code = err instanceof ApiError ? err.code : 'unknown';
      if (code === 'bad_password') setError('That password didn’t work. Check it and try again.');
      else if (code === 'rate_limited') {
        const wait = err instanceof ApiError && err.retryAfter ? fmtWait(err.retryAfter) : 'a minute';
        setError(`Too many tries in a row. Wait ${wait}, then try again.`);
      } else if (code === 'network') setError('Squint isn’t answering. Check your connection and try again.');
      else setError('Something went wrong on the server. Try again in a moment.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="gate" aria-labelledby="gate-title">
      <div className="gate-panel">
        <Mark size={44} className="gate-mark" />
        <h1 id="gate-title" className="gate-title">
          Squint is private
        </h1>
        <p className="gate-lede">Enter the shared password to start checking writing.</p>
        {note && <p className="gate-note">{note}</p>}
        <form className="gate-form" onSubmit={submit} noValidate>
          <TextInput
            type="password"
            label="Password"
            value={password}
            onChange={v => {
              setPassword(v);
              if (error) setError(null);
            }}
            status={error ? { type: 'error' } : undefined}
            hasAutoFocus
            ref={inputRef}
            {...({ autoComplete: 'current-password' } as Record<string, unknown>)}
          />
          <Button type="submit" label="Unlock" variant="primary" isLoading={busy} width="100%" />
        </form>
        <p id="gate-error" className="form-error" role="alert">
          {error && (
            <>
              <AlertIcon size={16} />
              <span>{error}</span>
            </>
          )}
        </p>
      </div>
    </section>
  );
}
