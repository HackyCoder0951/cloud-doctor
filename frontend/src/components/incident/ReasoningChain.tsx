'use client';
// SYMPTOM -> EVIDENCE -> CAUSE -> CODE PATH -> ACTION -> VERIFICATION. Every node is a button that opens the tab holding the detail,
// and every node says plainly when there is nothing behind it.
import { Untrusted } from '@/lib/untrusted';
import { problemOf, topHypothesis } from '@/lib/incident-view';
import type { IncidentBundle } from '@/lib/useIncidentBundle';
import type { TabId } from '@/components/views/IncidentDetail';

interface Node { key: string; label: string; value: string; sub?: string; tab: TabId; empty?: boolean }

export function ReasoningChain({ b, onTab }: { b: IncidentBundle; onTab: (t: TabId) => void }) {
  const i = b.incident;
  if (!i) return null;
  const d = b.diagnosis ?? undefined;
  const top = topHypothesis(d);
  const supporting = new Set(top?.claims.flatMap((c) => c.evidence) ?? []);
  const loc = b.code?.findings[0]?.locations[0];
  const plan = b.remediation?.plans[b.remediation.plans.length - 1];
  const ver = b.verification && b.verification.length > 0 ? b.verification[b.verification.length - 1] : undefined;
  const nodes: Node[] = [
    { key: 'symptom', label: 'Symptom', value: problemOf(i, d).text, tab: 'summary' },
    { key: 'evidence', label: 'Evidence', value: b.evidence ? `${b.evidence.length} collected` : 'loading', sub: top ? `${supporting.size} cited by the top hypothesis` : 'no hypothesis yet', tab: 'evidence', empty: !!b.evidence && b.evidence.length === 0 },
    { key: 'cause', label: 'Likely cause', value: top ? top.cause_id : 'none yet', sub: top ? `${top.service ?? 'service not stated'} · ${top.status}` : undefined, tab: 'diagnosis', empty: !top },
    { key: 'code', label: 'Code path', value: loc ? `${loc.file}:${loc.line_start}` : 'not available', sub: loc?.symbol, tab: 'code', empty: !loc },
    { key: 'action', label: 'Action', value: plan ? plan.action_id : d?.recommended_action ? `${d.recommended_action.action_id} (proposed)` : 'none', sub: plan ? `risk ${plan.risk_class}` : undefined, tab: 'remediation', empty: !plan && !d?.recommended_action },
    { key: 'verification', label: 'Verification', value: ver ? ver.verdict : 'not run', tab: 'verification', empty: !ver },
  ];
  return (
    <ol className="chain" aria-label="Reasoning chain" data-testid="reasoning-chain">
      {nodes.map((n, k) => (
        <li key={n.key} className="chain__item">
          <button type="button" className="chain__node" data-empty={n.empty ? 'true' : undefined} onClick={() => onTab(n.tab)}>
            <span className="chain__label">{n.label}</span>
            <span className="chain__value"><Untrusted value={n.value} max={80} /></span>
            {n.sub ? <span className="chain__sub"><Untrusted value={n.sub} max={80} /></span> : null}
          </button>
          {k < nodes.length - 1 ? <span className="chain__arrow" aria-hidden="true">→</span> : null}
        </li>
      ))}
    </ol>
  );
}
