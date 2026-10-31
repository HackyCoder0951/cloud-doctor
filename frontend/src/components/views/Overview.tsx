'use client';
import Link from 'next/link';
import { api } from '@/api/client';
import type { ServiceHealth } from '@/api/types';
import { ErrorNote, fmtNum, fmtTime, Loading } from '@/components/common';
import { IncidentStateBadge, MissingSignalBadge, StateBadge } from '@/components/badges';
import { useLiveReload } from '@/components/Live';
import { isIncidentId, isServiceName, Untrusted } from '@/lib/untrusted';
import { useApi } from '@/lib/useApi';

const STATE_ORDER = ['UNHEALTHY', 'DEGRADED', 'UNKNOWN', 'HEALTHY'] as const;

function Slis({ s }: { s: ServiceHealth }) {
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
          <span key={d.service} className={`dep st-${d.state}`}><Untrusted value={d.service} max={40} /> <small>{d.state}</small></span>
        ))}</p>
      ) : null}
      <p className="muted">updated {fmtTime(s.updated_at)}</p>
      <p>
        open incidents:{' '}
        {s.open_incident_ids.length === 0 ? 'none' : s.open_incident_ids.map((id) => (
          isIncidentId(id) ? <Link key={id} href={`/incidents/view/?id=${id}`}>{id} </Link> : <Untrusted key={id} value={id} max={20} />
        ))}
      </p>
    </article>
  );
}

export function Overview() {
  const services = useApi(() => api.listServices(), []);
  const incidents = useApi(() => api.listIncidents(), []);
  const reload = () => { services.reload(); incidents.reload(); };
  useLiveReload(reload, (e) => ['service.health', 'incident.opened', 'incident.updated', 'verification.finished', 'execution.finished'].includes(e.type));

  const list = [...(services.data ?? [])].sort((a, b) => STATE_ORDER.indexOf(a.state) - STATE_ORDER.indexOf(b.state) || a.name.localeCompare(b.name));
  const counts = STATE_ORDER.map((st) => [st, list.filter((s) => s.state === st).length] as const);
  const open = (incidents.data ?? []).filter((i) => i.state !== 'recovered' && i.state !== 'closed');

  return (
    <>
      <h1>Overview</h1>
      <ErrorNote error={services.error} what="Services" />
      {services.loading && !services.data ? <Loading what="services" /> : null}
      <p className="row counts">{counts.map(([st, n]) => <span key={st}><StateBadge state={st} /> {n}</span>)}</p>
      <section className="grid" aria-label="Service health">
        {list.map((s) => <ServiceCard key={s.name} s={s} />)}
      </section>
      <h2>Open incidents</h2>
      <ErrorNote error={incidents.error} what="Incidents" />
      {open.length === 0 && !incidents.loading ? <p className="muted">No open incidents.</p> : (
        <table className="table">
          <thead><tr><th>Incident</th><th>State</th><th>Severity</th><th>Services</th><th>Opened</th><th>Symptoms</th></tr></thead>
          <tbody>
            {open.map((i) => (
              <tr key={i.incident_id}>
                <td><Link href={`/incidents/view/?id=${i.incident_id}`}>{i.incident_id}</Link></td>
                <td><IncidentStateBadge state={i.state} /></td>
                <td>{i.severity}</td>
                <td>{i.services.map((s) => <Untrusted key={s} value={s} max={40} />).flatMap((el, k) => (k ? [', ', el] : [el]))}</td>
                <td>{fmtTime(i.opened_at)}</td>
                <td>{i.symptoms.map((s, k) => <div key={k}><Untrusted value={s} max={200} /></div>)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
