'use client';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, type ReactNode } from 'react';
import { api, onUnauthorized } from '@/api/client';
import { LiveProvider, useLive } from './Live';
import { StatusBanner } from './StatusBanner';

const NAV = [
  { href: '/', label: 'Overview' },
  { href: '/topology/', label: 'Topology' },
  { href: '/incidents/', label: 'Incidents' },
  { href: '/audit/', label: 'Audit' },
];

const CONN_LABEL = { open: 'Live: connected', connecting: 'Live: connecting…', reconnecting: 'Live: reconnecting…', closed: 'Live: offline' } as const;

export function ConnectionBadge() {
  const { state } = useLive();
  return <span className={`badge conn conn-${state}`} role="status" data-conn={state}>{CONN_LABEL[state]}</span>;
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
        <strong className="brand">Cloud Doctor</strong>
        <nav aria-label="Main">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href} aria-current={(n.href === '/' ? path === '/' : path.startsWith(n.href)) ? 'page' : undefined}>{n.label}</Link>
          ))}
        </nav>
        <span className="spacer" />
        <ConnectionBadge />
        <button type="button" onClick={logout}>Sign out</button>
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
