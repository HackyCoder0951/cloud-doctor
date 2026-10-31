'use client';
import Link from 'next/link';
import { useState } from 'react';
import { api } from '@/api/client';
import type { IncidentState } from '@/api/types';
import { ErrorNote, fmtTime } from '@/components/common';
import { IncidentStateBadge } from '@/components/badges';
import { useLiveReload } from '@/components/Live';
import { EmptyState, Pill, SeverityBadge, Skeleton } from '@/components/ui';
import { attentionScore, matchesFilter, needsHuman, parseBasis, pct, problemOf, QUEUE_FILTERS, SEVERITY_ORDER, topHypothesis, type QueueFilter } from '@/lib/incident-view';
import { isIncidentId, Untrusted } from '@/lib/untrusted';
import { useApi } from '@/lib/useApi';
import { useIncidentSignals } from '@/lib/useIncidentSignals';

export const INCIDENT_STATES: IncidentState[] = ['detected', 'investigating', 'diagnosed', 'remediating', 'verifying', 'recovered', 'escalated', 'closed'];

export function IncidentsList({ state, onStateChange }: { state: IncidentState | undefined; onStateChange: (s: IncidentState | undefined) => void }) {
  const { data, error, loading, reload } = useApi(() => api.listIncidents(state), [state]);
  useLiveReload(reload, (e) => e.type === 'incident.opened' || e.type === 'incident.updated');
  const [queue, setQueue] = useState<QueueFilter>('all');
  const [severity, setSeverity] = useState('');
  const [service, setService] = useState('');
  const signals = useIncidentSignals((data ?? []).map((i) => i.incident_id), data);

  const human = (id: string, st: Parameters<typeof needsHuman>[0]) => needsHuman(st, signals[id]?.remediation);
  const rows = (data ?? [])
    .filter((i) => matchesFilter(queue, i, human(i.incident_id, i)))
    .filter((i) => !severity || i.severity === severity)
    .filter((i) => !service || i.services.some((s) => s.includes(service.trim())))
    .sort((a, b) => attentionScore(b, human(b.incident_id, b)) - attentionScore(a, human(a.incident_id, a)) || (a.opened_at < b.opened_at ? 1 : -1));

  return (
    <>
      <h1>Incidents</h1>
      <div className="row" role="group" aria-label="Queue filter">
        {QUEUE_FILTERS.map((f) => <button key={f.id} type="button" className={queue === f.id ? '' : 'ghost'} aria-pressed={queue === f.id} onClick={() => setQueue(f.id)}>{f.label}</button>)}
        <span className="spacer" />
        <label className="inline">Severity{' '}
          <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
            <option value="">any</option>
            {SEVERITY_ORDER.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label className="inline">Service{' '}
          <input value={service} onChange={(e) => setService(e.target.value)} placeholder="name contains" maxLength={40} />
        </label>
        <label className="inline">
          State{' '}
          <select value={state ?? ''} onChange={(e) => onStateChange(e.target.value === '' ? undefined : (e.target.value as IncidentState))}>
            <option value="">all</option>
            {INCIDENT_STATES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
      </div>
      <ErrorNote error={error} what="Incidents" />
      {loading && !data ? <Skeleton label="incidents" lines={5} /> : null}
      {data && data.length === 0 ? <EmptyState title={`No incidents${state ? ` in state ${state}` : ''}`}>Nothing has been detected. The queue fills when the detector opens an incident.</EmptyState> : null}
      {data && data.length > 0 && rows.length === 0 ? <EmptyState title="No incidents match these filters">Clear a filter to see the rest of the queue.</EmptyState> : null}
      {rows.length > 0 ? (
        <div className="scroll">
          <table className="table queue">
            <thead><tr><th>ID</th><th>Severity</th><th>Problem</th><th>Affected services</th><th>State</th><th>Likely cause</th><th>Evidence</th><th>Opened</th><th>Outcome</th></tr></thead>
            <tbody>
              {rows.map((i) => {
                const sig = signals[i.incident_id];
                const top = topHypothesis(sig?.diagnosis ?? undefined);
                const basis = parseBasis(top);
                const h = human(i.incident_id, i);
                return (
                  <tr key={i.incident_id} data-testid={`inc-${i.incident_id}`}>
                    <td>{isIncidentId(i.incident_id) ? <Link className="mono" href={`/incidents/view/?id=${i.incident_id}`}>{i.incident_id}</Link> : <Untrusted value={i.incident_id} max={20} />}</td>
                    <td><SeverityBadge severity={i.severity} /></td>
                    <td><Untrusted value={problemOf(i, sig?.diagnosis ?? undefined).text} max={160} />{i.symptoms.length > 1 ? <span className="muted"> (+{i.symptoms.length - 1} more)</span> : null}</td>
                    <td><Untrusted value={i.services.join(' · ')} max={120} /></td>
                    <td>{h ? <Pill tone="warn" glyph="!">NEEDS HUMAN</Pill> : <IncidentStateBadge state={i.state} />}</td>
                    <td>{sig === undefined || sig.diagnosis === undefined ? <span className="muted">unknown</span> : top ? <code><Untrusted value={top.cause_id} max={60} /></code> : <span className="muted">none yet</span>}</td>
                    <td className="mono">{top ? pct(basis.coverage) ?? 'n/r' : '—'}</td>
                    <td>{fmtTime(i.opened_at)}</td>
                    <td>{i.outcome ?? '—'}{i.root_cause_confirmed ? ' (root cause confirmed)' : ''}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
      <p className="faint">Evidence = evidence coverage reported by the RCA engine; n/r means not reported. Sorted by need for a human, then severity.</p>
    </>
  );
}
