'use client';
import Link from 'next/link';
import { api } from '@/api/client';
import type { Topology as TopologyData } from '@/api/types';
import { ErrorNote, Loading } from '@/components/common';
import { StateBadge } from '@/components/badges';
import { useLiveReload } from '@/components/Live';
import { isServiceName, safeText } from '@/lib/untrusted';
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

export function TopologyGraph({ topology }: { topology: TopologyData }) {
  const { nodes, width, height } = layout(topology);
  const byName = new Map(nodes.map((n) => [n.name, n]));
  return (
    <svg className="topo" viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="img" aria-label="Service dependency graph">
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
        return <path key={i} className={`edge edge-${e.kind}`} data-edge-kind={e.kind} d={`M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`} fill="none" markerEnd="url(#arrow)" />;
      })}
      {nodes.map((n) => {
        const label = safeText(n.name, 24).text;
        const body = (
          <g className={`node st-${n.state}`} data-testid={`node-${n.name}`} data-state={n.state} transform={`translate(${n.x} ${n.y})`}>
            <rect width={NODE_W} height={NODE_H} rx="6" />
            <text x="10" y="19" className="node-name">{label}</text>
            <text x="10" y="36" className="node-state">{n.state}</text>
          </g>
        );
        return isServiceName(n.name) ? <Link key={n.name} href={`/services/view/?name=${n.name}`}>{body}</Link> : <g key={n.name}>{body}</g>;
      })}
    </svg>
  );
}

export function Topology() {
  const { data, error, loading, reload } = useApi(() => api.getTopology(), []);
  useLiveReload(reload, (e) => e.type === 'service.health');
  return (
    <>
      <h1>Topology</h1>
      <p className="muted">Generated from the service catalog. Solid arrows are hard dependencies, dashed arrows soft ones; an arrow points from a service to what it depends on.</p>
      <ErrorNote error={error} what="Topology" />
      {loading && !data ? <Loading what="topology" /> : null}
      {data ? (
        <>
          <div className="scroll"><TopologyGraph topology={data} /></div>
          <h2>Dependencies (text)</h2>
          <ul>
            {data.edges.map((e, i) => <li key={i}>{safeText(e.from, 40).text} → {safeText(e.to, 40).text} ({e.kind})</li>)}
          </ul>
          <p className="row">{data.nodes.map((n) => <span key={n.name}>{safeText(n.name, 40).text} <StateBadge state={n.state} /></span>)}</p>
        </>
      ) : null}
    </>
  );
}
