'use client';
import Link from 'next/link';
import { useState, type KeyboardEvent } from 'react';
import { api } from '@/api/client';
import type { Topology as TopologyData } from '@/api/types';
import { ErrorNote, fmtTime } from '@/components/common';
import { MissingSignalBadge, StateBadge } from '@/components/badges';
import { LogLines } from '@/components/LogLines';
import { useLiveReload } from '@/components/Live';
import { Slis } from '@/components/views/Overview';
import { EmptyState, Panel, Skeleton } from '@/components/ui';
import { isIncidentId, isServiceName, safeText, Untrusted } from '@/lib/untrusted';
import { useApi } from '@/lib/useApi';

const NODE_W = 132;
const NODE_H = 46;
const GAP_X = 90;
const GAP_Y = 26;
const MARGIN = 16;

export interface Placed { name: string; kind: string; state: TopologyData['nodes'][number]['state']; x: number; y: number }

/** Layered left-to-right layout: dependents on the left, what they depend on to the right. */
export function layout(t: TopologyData): { nodes: Placed[]; width: number; height: number } {
  const names = t.nodes.map((n) => n.name);
  const layer = new Map(names.map((n) => [n, 0]));
  for (let pass = 0; pass < names.length; pass++) {
    let changed = false;
    for (const e of t.edges) {
      if (!layer.has(e.from) || !layer.has(e.to)) continue;
      const want = (layer.get(e.from) ?? 0) + 1;
      if (want > (layer.get(e.to) ?? 0) && want < names.length) { layer.set(e.to, want); changed = true; }
    }
    if (!changed) break;
  }
  const cols = new Map<number, string[]>();
  for (const n of [...names].sort()) {
    const l = layer.get(n) ?? 0;
    cols.set(l, [...(cols.get(l) ?? []), n]);
  }
  const maxRows = Math.max(1, ...[...cols.values()].map((c) => c.length));
  const nodes: Placed[] = [];
  for (const [l, col] of cols) {
    col.forEach((name, row) => {
      const n = t.nodes.find((x) => x.name === name);
      if (n) nodes.push({ name, kind: n.kind, state: n.state, x: MARGIN + l * (NODE_W + GAP_X), y: MARGIN + row * (NODE_H + GAP_Y) });
    });
  }
  const nLayers = Math.max(1, ...[...cols.keys()].map((k) => k + 1));
  return { nodes, width: MARGIN * 2 + nLayers * NODE_W + (nLayers - 1) * GAP_X, height: MARGIN * 2 + maxRows * NODE_H + (maxRows - 1) * GAP_Y };
}

const STATE_GLYPH = { HEALTHY: '●', DEGRADED: '◐', UNHEALTHY: '✕', UNKNOWN: '?' } as const;

export function TopologyGraph({ topology, selected, onSelect }: { topology: TopologyData; selected?: string; onSelect?: (name: string) => void }) {
  const { nodes, width, height } = layout(topology);
  const byName = new Map(nodes.map((n) => [n.name, n]));
  return (
    <svg className="topo" viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="group" aria-label="Service dependency graph">
      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path className="arrowhead" d="M 0 0 L 10 5 L 0 10 z" />
        </marker>
      </defs>
      {topology.edges.map((e, i) => {
        const a = byName.get(e.from);
        const b = byName.get(e.to);
        if (!a || !b) return null;
        const x1 = a.x + NODE_W;
        const y1 = a.y + NODE_H / 2;
        const x2 = b.x;
        const y2 = b.y + NODE_H / 2;
        const mx = (x1 + x2) / 2;
        // A dependency that is down is the interesting edge: it is drawn heavier and dashed-red, and it is labelled in the side panel too.
        const failed = b.state === 'UNHEALTHY';
        return <path key={i} className={`edge edge-${e.kind}${failed ? ' edge-failed' : ''}`} data-edge-kind={e.kind} data-failed={failed ? 'true' : undefined} d={`M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`} fill="none" markerEnd="url(#arrow)" />;
      })}
      {nodes.map((n) => {
        const label = safeText(n.name, 24).text;
        const pick = () => onSelect?.(n.name);
        const key = (ev: KeyboardEvent) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); pick(); } };
        return (
          <g key={n.name} className={`node st-${n.state}${selected === n.name ? ' selected' : ''}`} data-testid={`node-${n.name}`} data-state={n.state} transform={`translate(${n.x} ${n.y})`}
            role={onSelect ? 'button' : undefined} tabIndex={onSelect ? 0 : undefined} aria-label={onSelect ? `${label}, ${n.state}. Show details` : undefined} aria-pressed={onSelect ? selected === n.name : undefined} onClick={onSelect ? pick : undefined} onKeyDown={onSelect ? key : undefined}>
            <rect width={NODE_W} height={NODE_H} rx="6" />
            <text x="10" y="19" className="node-name">{label}</text>
            <text x="10" y="36" className="node-state">{STATE_GLYPH[n.state]} {n.state}</text>
          </g>
        );
      })}
    </svg>
  );
}

function ServicePanel({ name, topology }: { name: string; topology: TopologyData }) {
  const services = useApi(() => api.listServices(), []);
  const logs = useApi(() => api.getServiceLogs(name, 300, 8), [name]);
  useLiveReload(() => { services.reload(); logs.reload(); }, (e) => e.type === 'service.health');
  const svc = services.data?.find((s) => s.name === name);
  const deps = topology.edges.filter((e) => e.from === name);
  const dependents = topology.edges.filter((e) => e.to === name);
  const stateOf = (n: string) => topology.nodes.find((x) => x.name === n)?.state ?? 'UNKNOWN';
  const incidentsOf = (n: string) => services.data?.find((s) => s.name === n)?.open_incident_ids ?? [];
  return (
    <aside className="side" aria-label={`Service ${name}`} data-testid="service-panel">
      <header className="row"><h2 className="side__title"><Untrusted value={name} max={60} /></h2><span className="spacer" />{isServiceName(name) ? <Link href={`/services/view/?name=${name}`}>Full service page →</Link> : null}</header>
      {!svc ? <Skeleton label="service" lines={3} /> : (
        <>
          <p className="row"><StateBadge state={svc.state} /> <MissingSignalBadge value={svc.missing_signal_state} withHelp /> <span className="muted">updated {fmtTime(svc.updated_at)}</span></p>
          <Slis s={svc} />
        </>
      )}
      <h4>Depends on</h4>
      {deps.length === 0 ? <p className="muted">nothing</p> : (
        <ul className="claims">{deps.map((e) => {
          const st = stateOf(e.to);
          return (
            <li key={e.to} data-failed={st === 'UNHEALTHY' ? 'true' : undefined}>
              <span aria-hidden="true">{STATE_GLYPH[st]} </span><Untrusted value={e.to} max={40} /> <span className="muted">({e.kind}, {st})</span>
              {st === 'UNHEALTHY' ? incidentsOf(e.to).filter(isIncidentId).map((id) => <span key={id}> <Link href={`/incidents/view/?id=${id}`}>{id} →</Link></span>) : null}
            </li>
          );
        })}</ul>
      )}
      <h4>Depended on by</h4>
      {dependents.length === 0 ? <p className="muted">nothing</p> : <ul className="claims">{dependents.map((e) => <li key={e.from}><span aria-hidden="true">{STATE_GLYPH[stateOf(e.from)]} </span><Untrusted value={e.from} max={40} /> <span className="muted">({stateOf(e.from)})</span></li>)}</ul>}
      <h4>Current incidents</h4>
      {svc && svc.open_incident_ids.length === 0 ? <p className="muted">none</p> : <ul className="claims">{(svc?.open_incident_ids ?? []).filter(isIncidentId).map((id) => <li key={id}><Link href={`/incidents/view/?id=${id}`}>{id}</Link> · <Link href={`/incidents/view/?id=${id}&tab=diagnosis`}>RCA</Link></li>)}</ul>}
      <h4>Recent changes</h4>
      <p className="muted">Not available: no deployment or change feed is connected.</p>
      <h4>Recent logs <span className="badge tag tag-untrusted">UNTRUSTED TEXT</span></h4>
      {logs.error ? <ErrorNote error={logs.error} what="Logs" /> : !logs.data ? <Skeleton label="logs" lines={2} /> : logs.data.lines.length === 0
        ? <p className="muted">No log lines (status: {logs.data.status}). Absence of logs is not evidence of health.</p> : <LogLines lines={logs.data.lines} />}
    </aside>
  );
}

export function Topology() {
  const { data, error, loading, reload } = useApi(() => api.getTopology(), []);
  useLiveReload(reload, (e) => e.type === 'service.health');
  const [selected, setSelected] = useState<string | undefined>(undefined);
  return (
    <>
      <h1>Topology</h1>
      <p className="muted">What depends on what, and where a failure is propagating. An arrow points from a service to what it depends on; solid arrows are hard dependencies, dashed arrows soft ones, and a heavy red arrow leads to a dependency that is down. Select a service for details.</p>
      <ErrorNote error={error} what="Topology" />
      {loading && !data ? <Skeleton label="topology" lines={4} /> : null}
      {data ? (
        <div className="topo-layout">
          <div className="scroll"><TopologyGraph topology={data} selected={selected} onSelect={setSelected} /></div>
          {selected ? <ServicePanel name={selected} topology={data} /> : <EmptyState title="No service selected">Select a service in the graph to see its health, dependencies, incidents and logs.</EmptyState>}
        </div>
      ) : null}
      {data ? (
        <Panel title="Dependencies (text)">
          <ul className="claims">{data.edges.map((e, i) => <li key={i}>{safeText(e.from, 40).text} → {safeText(e.to, 40).text} ({e.kind})</li>)}</ul>
          <p className="row">{data.nodes.map((n) => <span key={n.name}>{safeText(n.name, 40).text} <StateBadge state={n.state} /></span>)}</p>
        </Panel>
      ) : null}
    </>
  );
}
