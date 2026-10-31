'use client';
import { Tag } from '@/components/badges';
import { EvidenceLinks } from '@/components/EvidenceLink';
import { ReasoningChain } from '@/components/incident/ReasoningChain';
import { fmtNum } from '@/components/common';
import { EmptyState, EpistemicBadge, Meter, Panel, Skeleton } from '@/components/ui';
import type { TabId } from '@/components/views/IncidentDetail';
import { hypothesisEpistemic, knownFacts, parseBasis, pct, problemOf, topHypothesis, unknownFacts } from '@/lib/incident-view';
import { Untrusted } from '@/lib/untrusted';
import type { IncidentBundle } from '@/lib/useIncidentBundle';

export function SummaryTab({ b, onTab }: { b: IncidentBundle; onTab: (t: TabId) => void }) {
  const i = b.incident;
  if (!i) return <Skeleton label="summary" lines={4} />;
  const d = b.diagnosis;
  const top = topHypothesis(d ?? undefined);
  const basis = parseBasis(top);
  const supporting = [...new Set(top?.claims.flatMap((c) => c.evidence) ?? [])];
  const known = knownFacts(top);
  const unknown = unknownFacts(top);
  return (
    <section aria-label="Summary" className="stack">
      <Panel title="Reasoning chain"><ReasoningChain b={b} onTab={onTab} /></Panel>

      <div className="split">
        <Panel title="What happened">
          <p><Untrusted value={problemOf(i, d ?? undefined).text} max={300} /></p>
          {i.symptoms.length > 1 ? <ul className="claims">{i.symptoms.slice(1).map((s, k) => <li key={k}><Untrusted value={s} max={200} /></li>)}</ul> : null}
          <p className="faint">{i.symptoms.length} symptom{i.symptoms.length === 1 ? '' : 's'} reported across {i.services.length} service{i.services.length === 1 ? '' : 's'}.</p>
        </Panel>

        <Panel title="Likely cause" aside={top ? <EpistemicBadge kind={hypothesisEpistemic(top)} /> : undefined}>
          {d === undefined ? <Skeleton label="diagnosis" lines={3} /> : !top ? (
            <EmptyState title="No diagnosis yet">Cloud Doctor has not produced a hypothesis for this incident. Nothing here is a conclusion.</EmptyState>
          ) : (
            <div className="stack stack--tight">
              <p><code className="cause"><Untrusted value={top.cause_id} max={80} /></code> <Tag kind={`hyp-${top.status}`}>{top.status}</Tag></p>
              <p className="row" data-testid="cause-metrics">
                <span>Hypothesis ranking <Meter value={top.confidence} label="hypothesis ranking" /></span>
                <span>Evidence coverage <strong className="mono">{pct(basis.coverage) ?? 'not reported'}</strong></span>
                <span>Independent signal types <strong className="mono">{basis.signalTypes ?? 'not reported'}</strong></span>
                <span>Contradictions <strong className="mono">{top.contradicting.length}</strong></span>
              </p>
              <p className="faint">Ranking orders hypotheses by evidence weight. It is not a probability that the cause is true{top.confidence > 0 ? ` (${fmtNum(top.confidence, 2)} here)` : ''}.</p>
              <p>Supported by: {supporting.length ? <EvidenceLinks incident={i.incident_id} ids={supporting} /> : <span className="muted">no evidence cited</span>}</p>
              <p><button type="button" className="secondary" onClick={() => onTab('diagnosis')}>Open full RCA</button></p>
            </div>
          )}
        </Panel>
      </div>

      <div className="split">
        <Panel title="What Cloud Doctor knows" tone="ok">
          {known.length === 0 ? <p className="muted">No directly observed facts are recorded for the top hypothesis.</p> : (
            <ul className="facts-list">
              {known.map((k, n) => (
                <li key={n}><span aria-hidden="true" className="facts-list__mark">✓</span> <EpistemicBadge kind="OBSERVED" /> <Untrusted value={k.text} max={240} /> <span className="muted"><EvidenceLinks incident={i.incident_id} ids={k.evidence} /></span></li>
              ))}
            </ul>
          )}
        </Panel>
        <Panel title="What Cloud Doctor does not know" tone="warn">
          {unknown.length === 0 ? <p className="muted">No unknowns were listed. That does not mean there are none.</p> : (
            <ul className="facts-list">
              {unknown.map((u, n) => <li key={n}><span aria-hidden="true" className="facts-list__mark">?</span> <EpistemicBadge kind="UNKNOWN" /> <Untrusted value={u} max={240} /></li>)}
            </ul>
          )}
        </Panel>
      </div>
    </section>
  );
}
