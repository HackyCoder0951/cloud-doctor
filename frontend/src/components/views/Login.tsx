'use client';
import { useRouter } from 'next/navigation';
import { useState, type FormEvent } from 'react';
import { api, describeError } from '@/api/client';

export function Login() {
  const router = useRouter();
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.login(token);
      setToken('');
      router.replace('/');
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="login card" onSubmit={submit}>
      <h1>Cloud Doctor</h1>
      <p className="muted">Sign in with the shared MVP token. The API validates it and sets the session cookie; this page holds no credentials.</p>
      <label>
        Access token
        <input type="password" autoComplete="current-password" value={token} onChange={(e) => setToken(e.target.value)} minLength={8} maxLength={256} required />
      </label>
      <button type="submit" disabled={busy || token.length < 8}>{busy ? 'Signing in…' : 'Sign in'}</button>
      {error ? <p role="alert" className="error">{error}</p> : null}
    </form>
  );
}
