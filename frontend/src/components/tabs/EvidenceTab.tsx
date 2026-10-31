'use client';
import { useEffect, useRef, useState } from 'react';
import { api } from '@/api/client';
import type { Evidence } from '@/api/types';
import { ErrorNote, fmtTime } from '@/components/common';
import { LogLines, type LogLine } from '@/components/LogLines';
import { MissingSignalBadge, Tag } from '@/components/badges';
import { useLiveReload } from '@/components/Live';
import { EmptyState, Skeleton } from '@/components/ui';
import { evidenceRole, topHypothesis, type EvidenceRole } from '@/lib/incident-view';
import { jsonText, Untrusted } from '@/lib/untrusted';
import { useIncidentBundle } from '@/lib/useIncidentBundle';
import { useApi } from '@/lib/useApi';
import { EvidenceCard, useEvidenceDrawer } from '@/components/EvidenceDrawer';

function logLinesOf(payload: Record<string, unknown>): LogLine[] | null {
  const l = payload.lines;
  if (!Array.isArray(l)) return null;
  return l.map((x): LogLine => {
    const o = (x && typeof x === 'object' ? x : {}) as Record<string, unknown>;
    return { t: typeof o.t === 'string' ? o.t : undefined, line: typeof o.line === 'string' ? o.line : String(x), level: typeof o.level === 'string' ? o.level : undefined };
  });
}

export function Payload({ e }: { e: Evidence }) {
  const lines = logLinesOf(e.payload);
  const rest = Object.fromEntries(Object.entries(e.payload).filter(([k]) => k !== 'lines'));
  const j = jsonText(rest, 3000);
  return (
    <details>
      <summary>payload{lines ? ` (${lines.length} log lines)` : ''}</summary>
      {lines ? <LogLines lines={lines} /> : null}
      {Object.keys(rest).length > 0 || !lines ? <pre className="payload"><Untrusted value={j.text} max={3000} />{j.truncated ? <span className="trunc"> … [truncated, {j.originalLength} chars]</span> : null}</pre> : null}
    </details>
  );
}

const ROLE_FILTERS: { id: EvidenceRole | 'all'; label: string }[] = [
  { id: 'all', label: 'All' }, { id: 'supporting', label: 'Supporting' }, { id: 'contradicting', label: 'Contradicting' }, { id: 'context', label: 'Context' },
];

export function EvidenceTab({ incident, focus }: { incident: string; focus?: string }) {
  const { data, error, loading, reload } = useApi(() => api.getEvidence(incident), [incident]);
  const bundle = useIncidentBundle();
  const drawer = useEvidenceDrawer();
  const top = topHypothesis(bundle?.diagnosis ?? undefined);
  const [filter, setFilter] = useState<EvidenceRole | 'all'>('all');
  const shown = (data ?? []).filter((e) => filter === 'all' || evidenceRole(e.evidence_id, top) === filter);
  useLiveReload(reload, (e) => e.incident_id === incident);
  const focusRef = useRef<HTMLTableRowElement | null>(null);
  useEffect(() => {
    if (focus && data) focusRef.current?.scrollIntoView?.({ block: 'center' });
  }, [focus, data]);
  return (
    <section aria-label="Evidence">
      <ErrorNote error={error} what="Evidence" />
      {loading && !data ? <Skeleton label="evidence" lines={4} /> : null}
      {data && data.length > 0 ? (
        <>
          <div className="row" role="group" aria-label="Filter evidence by role">
            {ROLE_FILTERS.map((f) => <button key={f.id} type="button" className={filter === f.id ? '' : 'ghost'} aria-pressed={filter === f.id} onClick={() => setFilter(f.id)}>{f.label}</button>)}
            <span className="muted">{shown.length} of {data.length}{top ? ` · roles relative to the top hypothesis (${top.cause_id})` : ' · no hypothesis yet, so every item is context'}</span>
          </div>
          <div className="stack stack--tight evgrid" data-testid="evidence-cards">
            {shown.length === 0 ? <EmptyState title="Nothing in this group">No collected evidence has this role for the top hypothesis.</EmptyState> : shown.map((e) => (
              <EvidenceCard key={e.evidence_id} e={e} role={evidenceRole(e.evidence_id, top)} onOpen={(id) => (drawer ? drawer.open(id) : undefined)} />
            ))}
          </div>
          <h2>All fields</h2>
        </>
      ) : null}
      <p className="muted">Every value below is displayed as escaped plain text. Rows marked <Tag kind="untrusted">UNTRUSTED</Tag> contain text from monitored systems (for example log lines) that may be hostile; it is never interpreted.</p>
      <table className="table evidence">
        <thead><tr><th>ID</th><th>Source / type</th><th>Service</th><th>Status</th><th>Observed</th><th>Collected</th><th>Query</th><th>Summary</th><th>Payload</th><th>Hash</th></tr></thead>
        <tbody>
          {(data ?? []).map((e) => (
            <tr key={e.evidence_id} id={`ev-${e.evidence_id}`} ref={focus === e.evidence_id ? focusRef : undefined} className={focus === e.evidence_id ? 'focus' : undefined} data-focused={focus === e.evidence_id ? 'true' : undefined} data-testid={`ev-${e.evidence_id}`}>
              <td>{e.evidence_id}{e.untrusted ? <> <Tag kind="untrusted">UNTRUSTED</Tag></> : null}</td>
              <td><Untrusted value={`${e.source} / ${e.type}`} max={60} /></td>
              <td><Untrusted value={e.service} max={40} /></td>
              <td><span className={`badge es-${e.status}`}>{e.status}</span>{e.missing_signal_state ? <> <MissingSignalBadge value={e.missing_signal_state} /></> : null}</td>
              <td>{fmtTime(e.observed_at)}</td>
              <td>{fmtTime(e.collected_at)}</td>
              <td><code><Untrusted value={e.query} max={200} /></code></td>
              <td><Untrusted value={e.summary} max={300} /></td>
              <td><Payload e={e} /></td>
              <td><code title="payload_hash">{e.payload_hash.slice(0, 14)}…</code></td>
            </tr>
          ))}
        </tbody>
      </table>
      {data && data.length === 0 ? <p className="muted">No evidence collected.</p> : null}
    </section>
  );
}
