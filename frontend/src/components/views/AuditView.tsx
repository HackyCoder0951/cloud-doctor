'use client';
import Link from 'next/link';
import { useState } from 'react';
import { api } from '@/api/client';
import { ErrorNote, fmtTime, Loading } from '@/components/common';
import { useLiveReload } from '@/components/Live';
import { INCIDENT_ID_RE, isIncidentId, jsonText, Untrusted } from '@/lib/untrusted';
import { useApi } from '@/lib/useApi';

export function ChainBadge({ valid }: { valid: boolean }) {
  return valid
    ? <span className="badge chain-valid" data-chain-valid="true">✔ CHAIN VALID</span>
    : <span className="badge chain-broken" data-chain-valid="false">✖ CHAIN BROKEN</span>;
}

const short = (h: string) => `${h.slice(0, 14)}…`;

export function AuditView({ incident, onIncidentChange }: { incident: string | undefined; onIncidentChange: (id: string | undefined) => void }) {
  const [draft, setDraft] = useState(incident ?? '');
  const { data, error, loading, reload } = useApi(() => api.listAudit({ incident, limit: 100 }), [incident]);
  useLiveReload(reload, (e) => e.type === 'decision.recorded' || e.type === 'execution.finished' || e.type === 'incident.opened');
  const draftOk = draft === '' || INCIDENT_ID_RE.test(draft);
  return (
    <>
      <h1>Audit log</h1>
      <form className="inline" onSubmit={(e) => { e.preventDefault(); if (draftOk) onIncidentChange(draft === '' ? undefined : draft); }}>
        <label>Incident filter <input value={draft} onChange={(e) => setDraft(e.target.value.trim())} placeholder="INC-0001" maxLength={20} aria-invalid={!draftOk} /></label>{' '}
        <button type="submit" disabled={!draftOk}>Apply</button>
      </form>
      <ErrorNote error={error} what="Audit" />
      {loading && !data ? <Loading what="audit events" /> : null}
      {data ? (
        <>
          <p className="row" data-testid="chain-status">
            <ChainBadge valid={data.chain_valid} />
            <span className="muted">The hash chain is verified by the API; this page only reports the result.</span>
          </p>
          {!data.chain_valid ? <p role="alert" className="banner banner-failclosed">The audit hash chain did not verify. Treat the audit trail as potentially tampered and investigate before trusting it.</p> : null}
          <table className="table">
            <thead><tr><th>#</th><th>Time</th><th>Actor</th><th>Event</th><th>Incident</th><th>Detail (untrusted)</th><th>prev_hash</th><th>hash</th></tr></thead>
            <tbody>
              {data.events.map((e) => (
                <tr key={e.seq}>
                  <td>{e.seq}</td>
                  <td>{fmtTime(e.created_at)}</td>
                  <td><Untrusted value={e.actor} max={50} /></td>
                  <td><Untrusted value={e.event} max={60} /></td>
                  <td>{isIncidentId(e.incident_id) ? <Link href={`/incidents/view/?id=${e.incident_id}`}>{e.incident_id}</Link> : '—'}</td>
                  <td><code><Untrusted value={jsonText(e.detail, 300).text} max={300} /></code></td>
                  <td><code>{short(e.prev_hash)}</code></td>
                  <td><code>{short(e.hash)}</code></td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.events.length === 0 ? <p className="muted">No audit events.</p> : null}
        </>
      ) : null}
    </>
  );
}
