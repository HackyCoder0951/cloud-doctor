'use client';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { api, onUnauthorized } from '@/api/client';
import { isOpen } from '@/lib/incident-view';
import { useApi } from '@/lib/useApi';
import { LiveProvider, useLive, useLiveReload } from './Live';
import { StatusBanner } from './StatusBanner';

const NAV = [
  { href: '/', label: 'Overview' },
  { href: '/topology/', label: 'Topology' },
  { href: '/incidents/', label: 'Incidents' },
  { href: '/automation/', label: 'Automation' },
  { href: '/audit/', label: 'Audit' },
  { href: '/access/', label: 'Access' },
];

const CONN_LABEL = { open: 'Live: connected', connecting: 'Live: connecting…', reconnecting: 'Live: reconnecting…', closed: 'Live: offline' } as const;

export function ConnectionBadge() {
  const { state } = useLive();
  return <span className={`badge conn conn-${state}`} role="status" data-conn={state}>{CONN_LABEL[state]}</span>;
}

type Theme = 'dark' | 'light';
const THEME_KEY = 'cd-theme';

/** Per-viewer convenience only: the page renders correctly without storage, and dark is the default. */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>('dark');
  useEffect(() => {
    try { if (window.localStorage.getItem(THEME_KEY) === 'light') setTheme('light'); } catch { /* storage blocked: keep the default */ }
  }, []);
  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
  const flip = useCallback(() => {
    const next: Theme = theme === 'dark' ? 'light' : 'dark';
    setTheme(next);
    try { window.localStorage.setItem(THEME_KEY, next); } catch { /* ignore */ }
  }, [theme]);
  return <button type="button" className="ghost" onClick={flip} aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}>{theme === 'dark' ? '☾ Dark' : '☀ Light'}</button>;
}

/** The environment marker comes from build configuration, not from the API (the API has no such field yet). */
export const ENVIRONMENT = (process.env.NEXT_PUBLIC_CD_ENVIRONMENT ?? 'sandbox').toUpperCase();

export function OpenIncidentsChip() {
  const { data, error, reload } = useApi(() => api.listIncidents(), []);
  useLiveReload(reload, (e) => e.type === 'incident.opened' || e.type === 'incident.updated');
  const open = (data ?? []).filter(isOpen).length;
  if (!data) return <span className="count-chip" data-tone="unknown" title={error ? 'Incident count unavailable' : 'Loading incidents'}>{error ? 'incidents: unavailable' : 'incidents: …'}</span>;
  return <Link href="/incidents/" className="count-chip" data-tone={open > 0 ? 'bad' : 'ok'} data-testid="open-count">{open > 0 ? '▲' : '✓'} {open} open incident{open === 1 ? '' : 's'}</Link>;
}

function Chrome({ children }: { children: ReactNode }) {
  const router = useRouter();
  const path = usePathname() ?? '/';
  useEffect(() => onUnauthorized(() => router.replace('/login/')), [router]);
  const logout = async () => {
    try { await api.logout(); } catch { /* the session may already be gone */ }
    router.replace('/login/');
  };
  return (
    <>
      <header className="topbar">
        <strong className="brand"><span className="brand__mark" aria-hidden="true">+</span>Cloud Doctor</strong>
        <span className="env-marker" data-testid="environment" title="Environment marker from UI configuration. Remediation is restricted to sandbox-labelled containers by policy rule I-02 and re-checked by the actuator."><span aria-hidden="true">●</span> {ENVIRONMENT}</span>
        <nav aria-label="Main">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href} aria-current={(n.href === '/' ? path === '/' : path.startsWith(n.href)) ? 'page' : undefined}>{n.label}</Link>
          ))}
        </nav>
        <span className="spacer" />
        <OpenIncidentsChip />
        <ConnectionBadge />
        <ThemeToggle />
        <button type="button" className="ghost" onClick={logout}>Sign out</button>
      </header>
      <StatusBanner />
      <main>{children}</main>
    </>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const path = usePathname() ?? '/';
  if (path.startsWith('/login')) return <main>{children}</main>;
  return (
    <LiveProvider enabled>
      <Chrome>{children}</Chrome>
    </LiveProvider>
  );
}
