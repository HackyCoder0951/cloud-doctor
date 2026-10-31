'use client';
// What Cloud Doctor is allowed to do right now, from the only source the API offers: GET /status.
// Anything the API does not report (for example an auto-execution switch) is not shown as if it were.
import { api } from '@/api/client';
import type { SelfStatus } from '@/api/types';
import { ErrorNote } from '@/components/common';
import { useLiveReload } from '@/components/Live';
import { EmptyState, Panel, Pill, Skeleton, type Tone } from '@/components/ui';
import { Untrusted } from '@/lib/untrusted';
import { useApi } from '@/lib/useApi';

type Dep = SelfStatus['dependencies'][number];
const DEP_INFO: Record<Dep['name'], { title: string; role: string }> = {
  prometheus: { title: 'Metrics (Prometheus)', role: 'Detection and verification read metrics here. If it is down, health is UNKNOWN, never healthy.' },
  logs: { title: 'Logs (Loki)', role: 'Log evidence. Log text is untrusted and never drives a decision.' },
  database: { title: 'State database', role: 'Incidents, evidence and the audit chain. If it is down, actions are denied.' },
  actuator: { title: 'Actuator', role: 'The separate process that alone may execute a catalogue action, after re-checking policy.' },
  policy_layer2: { title: 'Policy layer 2', role: 'Client policy that can only tighten what layer 1 allows. When it is off, layer 1 alone decides.' },
  llm: { title: 'LLM assistance', role: 'Optional. Diagnosis, recovery and verification work without it.' },
};
const TONE: Record<Dep['state'], { tone: Tone; glyph: string; label: string }> = {
  up: { tone: 'ok', glyph: '✓', label: 'ACTIVE' }, down: { tone: 'bad', glyph: '✕', label: 'DOWN' }, disabled: { tone: 'unknown', glyph: '–', label: 'OFF' }, unknown: { tone: 'warn', glyph: '?', label: 'UNKNOWN' },
};

export function AutomationView() {
  const { data, error, reload } = useApi(() => api.getStatus(), []);
  useLiveReload(reload, (e) => e.type === 'status.changed');
  return (
    <>
      <h1>Automation</h1>
      <p className="muted">What Cloud Doctor can do right now, and which safety components it depends on. This page reports the API's own self-status; it cannot change anything.</p>
      <ErrorNote error={error} what="Status" />
      {!data && !error ? <Skeleton label="status" lines={4} /> : null}
      {error && !data ? <EmptyState title="Status unavailable">Treat automation as stopped (fail closed) until the API answers.</EmptyState> : null}
      {data ? (
        <>
          <p className="row" data-testid="overall">
            Overall: <Pill tone={data.state === 'ok' ? 'ok' : data.state === 'degraded' ? 'warn' : 'bad'} glyph={data.state === 'ok' ? '✓' : '!'}>{data.state === 'fail_closed' ? 'FAIL CLOSED' : data.state.toUpperCase()}</Pill>
            <span className="muted">{data.state === 'fail_closed' ? 'A safety dependency is unavailable, so remediation is denied.' : data.state === 'degraded' ? 'Some dependencies are impaired; evidence may be incomplete.' : 'All reported dependencies are up.'}</span>
          </p>
          <div className="grid">
            {data.dependencies.map((d) => {
              const t = TONE[d.state];
              const info = DEP_INFO[d.name];
              return (
                <Panel key={d.name} title={info?.title ?? d.name} aside={<Pill tone={t.tone} glyph={t.glyph}>{t.label}</Pill>}>
                  <p className="muted">{info?.role}</p>
                  {d.detail ? <p><Untrusted value={d.detail} max={200} /></p> : null}
                </Panel>
              );
            })}
          </div>
          <h2>Operating rules</h2>
          <ul className="claims">
            <li>Actions come only from a fixed catalogue and run only on sandbox-labelled containers.</li>
            <li>Medium-risk actions need an operator approval bound to the exact plan; high-risk actions never execute.</li>
            <li>Policy is re-evaluated by the actuator at execution time. A missing or failed check is a denial.</li>
            <li>The API does not report an auto-execution switch, so none is shown here.</li>
          </ul>
        </>
      ) : null}
    </>
  );
}
