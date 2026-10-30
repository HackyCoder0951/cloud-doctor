'use client';
import Link from 'next/link';
import { api } from '@/api/client';
import type { IncidentState } from '@/api/types';
import { ErrorNote, fmtTime, Loading } from '@/components/common';
import { IncidentStateBadge } from '@/components/badges';
import { useLiveReload } from '@/components/Live';
import { Untrusted } from '@/lib/untrusted';
import { useApi } from '@/lib/useApi';

export const INCIDENT_STATES: IncidentState[] = ['detected', 'investigating', 'diagnosed', 'remediating', 'verifying', 'recovered', 'escalated', 'closed'];

export function IncidentsList({ state, onStateChange }: { state: IncidentState | undefined; onStateChange: (s: IncidentState | undefined) => void }) {
  const { data, error, loading, reload } = useApi(() => api.listIncidents(state), [state]);
  useLiveReload(reload, (e) => e.type === 'incident.opened' || e.type === 'incident.updated');
  return (
    <>
      <h1>Incidents</h1>
      <label className="inline">
        State{' '}
        <select value={state ?? ''} onChange={(e) => onStateChange(e.target.value === '' ? undefined : (e.target.value as IncidentState))}>
          <option value="">all</option>
          {INCIDENT_STATES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </label>
      <ErrorNote error={error} what="Incidents" />
      {loading && !data ? <Loading what="incidents" /> : null}
      {data && data.length === 0 ? <p className="muted">No incidents{state ? ` in state ${state}` : ''}.</p> : null}
      {data && data.length > 0 ? (
        <table className="table">
          <thead><tr><th>Incident</th><th>State</th><th>Severity</th><th>Services</th><th>Opened</th><th>Outcome</th><th>Symptoms</th></tr></thead>
          <tbody>
            {data.map((i) => (
              <tr key={i.incident_id} data-testid={`inc-${i.incident_id}`}>
                <td><Link href={`/incidents/view/?id=${i.incident_id}`}>{i.incident_id}</Link></td>
                <td><IncidentStateBadge state={i.state} /></td>
                <td>{i.severity}</td>
                <td>{i.services.join(', ')}</td>
                <td>{fmtTime(i.opened_at)}</td>
                <td>{i.outcome ?? '—'}{i.root_cause_confirmed ? ' (root cause confirmed)' : ''}</td>
                <td>{i.symptoms.map((s, k) => <div key={k}><Untrusted value={s} max={160} /></div>)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </>
  );
}
