'use client';
import { api } from '@/api/client';
import { ErrorNote, fmtTime, lagSeconds, Loading } from '@/components/common';
import { EvidenceLinks } from '@/components/EvidenceLink';
import { useLiveReload } from '@/components/Live';
import { Tag } from '@/components/badges';
import { Untrusted } from '@/lib/untrusted';
import { useApi } from '@/lib/useApi';

export function TimelineTab({ incident }: { incident: string }) {
  const { data, error, loading, reload } = useApi(() => api.getTimeline(incident), [incident]);
  useLiveReload(reload, (e) => e.incident_id === incident && (e.type === 'timeline.event' || e.type === 'incident.updated'));
  // The API returns events ordered by event_time; sort again so the invariant never depends on it.
  const events = [...(data ?? [])].sort((a, b) => Date.parse(a.event_time) - Date.parse(b.event_time) || a.event_id.localeCompare(b.event_id));
  return (
    <section aria-label="Timeline">
      <ErrorNote error={error} what="Timeline" />
      {loading && !data ? <Loading what="timeline" /> : null}
      <p className="muted">Ordered by event time. “collected” is when Cloud Doctor learned of the event; suppressed events stay in the timeline (suppression affects notification only).</p>
      <table className="table timeline">
        <thead><tr><th>Event time</th><th>Collected at</th><th>Kind</th><th>Service</th><th>Summary</th><th>Evidence</th></tr></thead>
        <tbody>
          {events.map((e) => {
            const lag = lagSeconds(e.event_time, e.collected_at);
            return (
              <tr key={e.event_id} className={e.suppressed ? 'suppressed' : undefined} data-suppressed={e.suppressed ? 'true' : undefined} data-testid={`tl-${e.event_id}`}>
                <td>{fmtTime(e.event_time)}</td>
                <td>{fmtTime(e.collected_at)}{lag && lag > 0 ? <span className="muted"> (+{lag}s)</span> : null}</td>
                <td><Tag kind="kind">{e.kind}</Tag></td>
                <td>{e.service ? <Untrusted value={e.service} max={40} /> : '—'}</td>
                <td><Untrusted value={e.summary} max={300} />{e.suppressed ? <> <Tag kind="suppressed">SUPPRESSED</Tag></> : null}</td>
                <td><EvidenceLinks incident={incident} ids={e.evidence_refs} /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {data && data.length === 0 ? <p className="muted">No timeline events yet.</p> : null}
    </section>
  );
}
