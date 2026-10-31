'use client';
import Link from 'next/link';
import { api } from '@/api/client';
import type { HealthState, Incident, ServiceHealth } from '@/api/types';
import { ErrorNote, fmtNum, fmtTime } from '@/components/common';
import { IncidentStateBadge, MissingSignalBadge, StateBadge, Tag } from '@/components/badges';
import { useLiveReload } from '@/components/Live';
import { EmptyState, Pill, SeverityBadge, Skeleton } from '@/components/ui';
import { attentionScore, isOpen, needsHuman, parseBasis, pct, pendingApprovals, problemOf, topHypothesis } from '@/lib/incident-view';
import { isIncidentId, isServiceName, Untrusted } from '@/lib/untrusted';
import { useApi } from '@/lib/useApi';
import { idsToWatch, useIncidentSignals, type Signals } from '@/lib/useIncidentSignals';

const STATE_ORDER = ['UNHEALTHY', 'DEGRADED', 'UNKNOWN', 'HEALTHY'] as const;
const DEP_GLYPH: Record<HealthState, string> = { HEALTHY: '●', DEGRADED: '◐', UNHEALTHY: '✕', UNKNOWN: '?' };

export function Slis({ s }: { s: ServiceHealth }) {
  if (!s.slis || Object.keys(s.slis).length === 0) {
    return <p className="muted">{s.state === 'UNKNOWN' ? 'No SLIs: state is UNKNOWN (never assumed healthy).' : 'No SLIs reported.'}</p>;
  }
  const x = s.slis;
  return (
    <dl className="slis">
      {x.availability !== undefined ? <><dt>availability</dt><dd>{fmtNum(x.availability * 100, 2)}%</dd></> : null}
      {x.error_ratio !== undefined ? <><dt>error ratio</dt><dd>{fmtNum(x.error_ratio, 4)}</dd></> : null}
      {x.latency_p95_seconds !== undefined ? <><dt>p95 latency</dt><dd>{fmtNum(x.latency_p95_seconds, 3)} s</dd></> : null}
      {x.throughput_rps !== undefined ? <><dt>throughput</dt><dd>{fmtNum(x.throughput_rps, 1)} rps</dd></> : null}
      {x.queue_depth !== undefined ? <><dt>queue depth</dt><dd>{fmtNum(x.queue_depth, 0)}</dd></> : null}
    </dl>
  );
}

export function ServiceCard({ s }: { s: ServiceHealth }) {
  return (
    <article className={`card svc st-${s.state}`} data-testid={`svc-${s.name}`} data-state={s.state}>
      <header>
        <h3>{isServiceName(s.name) ? <Link href={`/services/view/?name=${s.name}`}>{s.name}</Link> : <Untrusted value={s.name} max={60} />}</h3>
        <span className="muted"><Untrusted value={s.kind} max={40} /></span>
      </header>
      <div className="row">
        <StateBadge state={s.state} />
        <MissingSignalBadge value={s.missing_signal_state} />
      </div>
      <Slis s={s} />
      {s.dependencies && s.dependencies.length > 0 ? (
        <p className="deps">depends on: {s.dependencies.map((d) => (
          <span key={d.service} className={`dep st-${d.state}`}><span aria-hidden="true">{DEP_GLYPH[d.state]} </span><Untrusted value={d.service} max={40} /> <small>{d.state}</small></span>
        ))}</p>
      ) : null}
      <p className="muted">updated {fmtTime(s.updated_at)}</p>
      <p>
        open incidents:{' '}
        {s.open_incident_ids.length === 0 ? 'none' : s.open_incident_ids.map((id) => (
          isIncidentId(id) ? <Link key={id} href={`/incidents/view/?id=${id}`}>{id} · Investigate →{' '}</Link> : <Untrusted key={id} value={id} max={20} />
        ))}
      </p>
    </article>
  );
}

function Tile({ label, value, tone, hint }: { label: string; value: string | number; tone: 'bad' | 'warn' | 'ok' | 'unknown'; hint?: string }) {
  return (
    <div className="tile" data-tone={tone} title={hint} data-testid={`tile-${label.toLowerCase().replace(/\s+/g, '-')}`}>
      <span className="tile__value mono">{value}</span>
      <span className="tile__label">{label}</span>
    </div>
  );
}

export function NeedsAttentionCard({ i, sig }: { i: Incident; sig: Signals | undefined }) {
  const human = needsHuman(i, sig?.remediation);
  const top = topHypothesis(sig?.diagnosis ?? undefined);
  const basis = parseBasis(top);
  return (
    <article className="attn" data-severity={i.severity} data-testid={`attn-${i.incident_id}`}>
      <div className="row">
        <SeverityBadge severity={i.severity} />
        {human ? <Pill tone="warn" glyph="!">NEEDS HUMAN</Pill> : <IncidentStateBadge state={i.state} />}
        <span className="spacer" />
        <span className="mono muted">{i.incident_id} · {fmtTime(i.opened_at)}</span>
      </div>
      <h3 className="attn__title"><Untrusted value={problemOf(i, sig?.diagnosis ?? undefined).text} max={160} /></h3>
      <p className="muted"><Untrusted value={i.services.join(' · ')} max={120} /></p>
      <p className="attn__cause">
        <span className="muted">Likely cause</span>{' '}
        {sig === undefined || sig.diagnosis === undefined ? <span className="muted">unknown (diagnosis not loaded)</span>
          : top ? <><code>{top.cause_id}</code> <span className="muted">· evidence coverage {pct(basis.coverage) ?? 'not reported'}</span></>
          : <span className="muted">no diagnosis yet</span>}
      </p>
      {isIncidentId(i.incident_id) ? <p><Link className="attn__link" href={`/incidents/view/?id=${i.incident_id}`}>View investigation →</Link></p> : null}
    </article>
  );
}

export function Overview() {
  const services = useApi(() => api.listServices(), []);
  const incidents = useApi(() => api.listIncidents(), []);
  const reload = () => { services.reload(); incidents.reload(); };
  useLiveReload(reload, (e) => ['service.health', 'incident.opened', 'incident.updated', 'verification.finished', 'execution.finished', 'decision.recorded'].includes(e.type));

  const watch = idsToWatch(incidents.data);
  const signals = useIncidentSignals(watch, incidents.data);

  const list = [...(services.data ?? [])].sort((a, b) => STATE_ORDER.indexOf(a.state) - STATE_ORDER.indexOf(b.state) || a.name.localeCompare(b.name));
  const count = (st: HealthState) => list.filter((s) => s.state === st).length;
  const open = (incidents.data ?? []).filter(isOpen);
  const ranked = [...open].sort((a, b) => attentionScore(b, needsHuman(b, signals[b.incident_id]?.remediation)) - attentionScore(a, needsHuman(a, signals[a.incident_id]?.remediation)));
  const loaded = open.every((i) => signals[i.incident_id]?.remediation !== undefined);
  const pending = open.reduce((n, i) => n + pendingApprovals(signals[i.incident_id]?.remediation).length, 0);
  const recovering = open.filter((i) => i.state === 'remediating' || i.state === 'verifying').length;
  const recent = Object.entries(signals)
    .flatMap(([id, s]) => (s.remediation?.executions ?? []).map((x) => ({ id, x, action: s.remediation?.plans.find((p) => p.plan_id === x.plan_id)?.action_id })))
    .sort((a, b) => Date.parse(b.x.started_at) - Date.parse(a.x.started_at)).slice(0, 6);

  return (
    <>
      <h1>Overview</h1>
      <p className="muted">Infrastructure situation overview</p>
      <ErrorNote error={services.error} what="Services" />
      <ErrorNote error={incidents.error} what="Incidents" />
      {(services.loading && !services.data) || (incidents.loading && !incidents.data) ? <Skeleton label="overview" lines={4} /> : null}

      <section className="tiles" aria-label="Situation counts">
        <Tile label="Open incidents" value={open.length} tone={open.length ? 'bad' : 'ok'} />
        <Tile label="Critical incidents" value={open.filter((i) => i.severity === 'critical').length} tone={open.some((i) => i.severity === 'critical') ? 'bad' : 'ok'} />
        <Tile label="Unhealthy services" value={count('UNHEALTHY')} tone={count('UNHEALTHY') ? 'bad' : 'ok'} />
        <Tile label="Degraded services" value={count('DEGRADED')} tone={count('DEGRADED') ? 'warn' : 'ok'} />
        <Tile label="Pending approvals" value={loaded ? pending : '…'} tone={pending ? 'warn' : 'ok'} hint={loaded ? undefined : 'Some incidents have not reported their remediation state yet'} />
        <Tile label="Active recoveries" value={recovering} tone={recovering ? 'warn' : 'ok'} />
      </section>
      <p className="faint">Services with unknown health: {count('UNKNOWN')}. Unknown is counted separately and is never treated as healthy.</p>

      <h2>Needs attention</h2>
      {open.length === 0 && !incidents.loading ? (
        <EmptyState title="No active incidents">All monitored services that report data are healthy or unaffected. Services with no data are listed below as UNKNOWN.</EmptyState>
      ) : (
        <div className="attn-grid" data-testid="needs-attention">
          {ranked.slice(0, 4).map((i) => <NeedsAttentionCard key={i.incident_id} i={i} sig={signals[i.incident_id]} />)}
        </div>
      )}

      <h2>Active incidents</h2>
      {open.length === 0 && !incidents.loading ? <p className="muted">No open incidents.</p> : (
        <div className="scroll">
          <table className="table">
            <thead><tr><th>Incident</th><th>State</th><th>Severity</th><th>Services</th><th>Opened</th><th>Symptoms</th></tr></thead>
            <tbody>
              {open.map((i) => (
                <tr key={i.incident_id}>
                  <td>{isIncidentId(i.incident_id) ? <Link href={`/incidents/view/?id=${i.incident_id}`}>{i.incident_id}</Link> : <Untrusted value={i.incident_id} max={20} />}</td>
                  <td><IncidentStateBadge state={i.state} /></td>
                  <td><SeverityBadge severity={i.severity} /></td>
                  <td>{i.services.map((s) => <Untrusted key={s} value={s} max={40} />).flatMap((el, k) => (k ? [', ', el] : [el]))}</td>
                  <td>{fmtTime(i.opened_at)}</td>
                  <td>{i.symptoms.map((s, k) => <div key={k}><Untrusted value={s} max={200} /></div>)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2>Service health</h2>
      <section className="grid" aria-label="Service health">
        {list.map((s) => <ServiceCard key={s.name} s={s} />)}
      </section>

      <h2>Recent recovery actions</h2>
      {recent.length === 0 ? <p className="muted">No recovery actions recorded for recent incidents.</p> : (
        <ul className="claims" data-testid="recent-actions">
          {recent.map(({ id, x, action }) => (
            <li key={x.execution_id}>
              <span className="mono muted">{fmtTime(x.started_at)}</span> <code>{action ?? 'action'}</code> <Tag kind={`ex-${x.result}`}>{x.result}</Tag>{' '}
              {isIncidentId(id) ? <Link href={`/incidents/view/?id=${id}`}>{id}</Link> : null}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
