'use client';
import Link from 'next/link';
import { api } from '@/api/client';
import type { MetricName } from '@/api/types';
import { ErrorNote, fmtTime, Loading } from '@/components/common';
import { MissingSignalBadge, StateBadge } from '@/components/badges';
import { LogLines } from '@/components/LogLines';
import { useLiveReload } from '@/components/Live';
import { Sparkline } from '@/components/Sparkline';
import { isIncidentId, Untrusted } from '@/lib/untrusted';
import { useApi } from '@/lib/useApi';

export const METRICS: { name: MetricName; label: string }[] = [
  { name: 'error_ratio', label: 'error ratio' },
  { name: 'latency_p95_seconds', label: 'p95 latency (s)' },
  { name: 'throughput_rps', label: 'throughput (rps)' },
  { name: 'queue_depth', label: 'queue depth' },
  { name: 'up', label: 'up' },
];

function Metric({ service, name, label }: { service: string; name: MetricName; label: string }) {
  const { data, error, reload } = useApi(() => api.getServiceMetric(service, name), [service, name]);
  useLiveReload(reload, (e) => e.type === 'service.health' && e.service === service);
  if (error) return <ErrorNote error={error} what={label} />;
  if (!data) return <Loading what={label} />;
  return <Sparkline series={data} label={label} />;
}

export function ServiceDetail({ service }: { service: string }) {
  const health = useApi(() => api.getServiceHealth(service), [service]);
  const logs = useApi(() => api.getServiceLogs(service), [service]);
  useLiveReload(() => { health.reload(); logs.reload(); }, (e) => e.type === 'service.health' && e.service === service);
  const h = health.data;
  return (
    <>
      <h1><Untrusted value={service} max={60} /></h1>
      <p><Link href="/">← Overview</Link></p>
      <ErrorNote error={health.error} what="Service" />
      {h ? (
        <p className="row">
          <StateBadge state={h.state} /> <MissingSignalBadge value={h.missing_signal_state} withHelp /> <span className="muted">updated {fmtTime(h.updated_at)}</span>
          {h.open_incident_ids.map((id) => (isIncidentId(id) ? <Link key={id} href={`/incidents/view/?id=${id}`}>{id}</Link> : null))}
        </p>
      ) : null}
      <h2>Metrics (last 10 minutes)</h2>
      <div className="sparks">{METRICS.map((m) => <Metric key={m.name} service={service} name={m.name} label={m.label} />)}</div>
      <h2>Logs <span className="badge tag tag-untrusted">UNTRUSTED TEXT</span></h2>
      <ErrorNote error={logs.error} what="Logs" />
      {logs.data ? (
        logs.data.lines.length === 0 ? <p className="muted">No log lines (status: {logs.data.status}). Absence of logs is not evidence of health.</p> : <LogLines lines={logs.data.lines} />
      ) : <Loading what="logs" />}
    </>
  );
}
