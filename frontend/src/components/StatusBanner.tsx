'use client';
import { useEffect } from 'react';
import { api } from '@/api/client';
import { Untrusted } from '@/lib/untrusted';
import { useApi } from '@/lib/useApi';
import { useLiveReload } from './Live';

/** Self-health of Cloud Doctor itself (/status). Degraded and fail-closed states are always visible. */
export function StatusBanner() {
  const { data, error, reload } = useApi(() => api.getStatus(), []);
  useLiveReload(reload, (e) => e.type === 'status.changed');
  useEffect(() => {
    const t = setInterval(reload, 15_000);
    return () => clearInterval(t);
  }, [reload]);

  if (error && !data) {
    return <div role="alert" className="banner banner-failclosed" data-status="unreachable"><strong>Cloud Doctor status unavailable.</strong> Treat automation as stopped (fail closed) until the API answers.</div>;
  }
  if (!data || data.state === 'ok') return data ? <div className="status-ok" data-status="ok" role="status">System status: OK</div> : null;
  const bad = data.dependencies.filter((d) => d.state === 'down' || d.state === 'unknown');
  const failClosed = data.state === 'fail_closed';
  return (
    <div role="alert" className={failClosed ? 'banner banner-failclosed' : 'banner banner-degraded'} data-status={data.state}>
      <strong>{failClosed ? 'FAIL CLOSED' : 'DEGRADED MODE'}</strong>
      {failClosed
        ? ': a safety dependency is unavailable, so remediation actions are denied. Diagnosis and display may be stale.'
        : ': some dependencies are impaired. Evidence may be incomplete and missing data is shown as UNKNOWN, not healthy.'}
      {bad.length > 0 ? (
        <ul>
          {bad.map((d) => (
            <li key={d.name}><code>{d.name}</code> {d.state}{d.detail ? <> — <Untrusted value={d.detail} max={200} /></> : null}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
