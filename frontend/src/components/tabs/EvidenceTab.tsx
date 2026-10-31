'use client';
import { useEffect, useRef } from 'react';
import { api } from '@/api/client';
import type { Evidence } from '@/api/types';
import { ErrorNote, fmtTime, Loading } from '@/components/common';
import { LogLines, type LogLine } from '@/components/LogLines';
import { MissingSignalBadge, Tag } from '@/components/badges';
import { useLiveReload } from '@/components/Live';
import { jsonText, Untrusted } from '@/lib/untrusted';
import { useApi } from '@/lib/useApi';

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

export function EvidenceTab({ incident, focus }: { incident: string; focus?: string }) {
  const { data, error, loading, reload } = useApi(() => api.getEvidence(incident), [incident]);
  useLiveReload(reload, (e) => e.incident_id === incident);
  const focusRef = useRef<HTMLTableRowElement | null>(null);
  useEffect(() => {
    if (focus && data) focusRef.current?.scrollIntoView?.({ block: 'center' });
  }, [focus, data]);
  return (
    <section aria-label="Evidence">
      <ErrorNote error={error} what="Evidence" />
      {loading && !data ? <Loading what="evidence" /> : null}
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
