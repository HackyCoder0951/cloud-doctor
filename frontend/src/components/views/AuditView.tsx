'use client';
import Link from 'next/link';
import { useState } from 'react';
import { api } from '@/api/client';
import { ErrorNote, fmtTime } from '@/components/common';
import { useLiveReload } from '@/components/Live';
import { EvidenceLinks } from '@/components/EvidenceLink';
import { Skeleton } from '@/components/ui';
import { EVIDENCE_ID_RE, INCIDENT_ID_RE, isIncidentId, jsonText, Untrusted } from '@/lib/untrusted';
import { useApi } from '@/lib/useApi';

export function ChainBadge({ valid }: { valid: boolean }) {
  return valid
    ? <span className="badge chain-valid" data-chain-valid="true">✔ CHAIN VALID</span>
    : <span className="badge chain-broken" data-chain-valid="false">✖ CHAIN BROKEN</span>;
}

const short = (h: string) => `${h.slice(0, 14)}…`;

/** Result and evidence come from the event's own detail. When the detail does not carry them the cell says so; nothing is inferred. */
function resultOf(detail: Record<string, unknown>): string | undefined {
  for (const k of ['result', 'final', 'verdict', 'state']) { const v = detail[k]; if (typeof v === 'string' && v) return v; }
  return undefined;
}
function evidenceOf(detail: Record<string, unknown>): string[] {
  for (const k of ['evidence_ids', 'evidence_refs', 'evidence']) {
    const v = detail[k];
    if (Array.isArray(v)) return v.filter((x): x is string => typeof x === 'string' && EVIDENCE_ID_RE.test(x));
  }
  return [];
}

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
      {loading && !data ? <Skeleton label="audit events" lines={5} /> : null}
      {data ? (
        <>
          <p className="row" data-testid="chain-status">
            <ChainBadge valid={data.chain_valid} />
            <span className="muted">The hash chain is verified by the API; this page only reports the result.</span>
          </p>
          {!data.chain_valid ? <p role="alert" className="banner banner-failclosed">The audit hash chain did not verify. Treat the audit trail as potentially tampered and investigate before trusting it.</p> : null}
          <table className="table">
            <thead><tr><th>#</th><th>Time</th><th>Actor</th><th>Action</th><th>Target</th><th>Result</th><th>Evidence</th><th>Detail (untrusted)</th><th>prev_hash</th><th>hash</th></tr></thead>
            <tbody>
              {data.events.map((e) => (
                <tr key={e.seq}>
                  <td>{e.seq}</td>
                  <td>{fmtTime(e.created_at)}</td>
                  <td><Untrusted value={e.actor} max={50} /></td>
                  <td><Untrusted value={e.event} max={60} /></td>
                  <td>{isIncidentId(e.incident_id) ? <Link href={`/incidents/view/?id=${e.incident_id}`}>{e.incident_id}</Link> : '—'}</td>
                  <td>{resultOf(e.detail) ? <Untrusted value={resultOf(e.detail)} max={40} /> : <span className="muted">not recorded</span>}</td>
                  <td>{isIncidentId(e.incident_id) && evidenceOf(e.detail).length ? <EvidenceLinks incident={e.incident_id} ids={evidenceOf(e.detail)} /> : <span className="muted">—</span>}</td>
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
