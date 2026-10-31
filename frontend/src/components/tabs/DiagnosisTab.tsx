'use client';
import { useRef, useState } from 'react';
import { api, ApiError, describeError, newIdempotencyKey } from '@/api/client';
import type { Claim, Diagnosis, Hypothesis } from '@/api/types';
import { ErrorNote, fmtTime } from '@/components/common';
import { EvidenceLinks } from '@/components/EvidenceLink';
import { ReasoningChain } from '@/components/incident/ReasoningChain';
import { useLiveReload } from '@/components/Live';
import { Tag } from '@/components/badges';
import { EmptyState, EpistemicBadge, Meter, Panel, Skeleton } from '@/components/ui';
import type { TabId } from '@/components/views/IncidentDetail';
import { claimEpistemic, hypothesisEpistemic, parseBasis, pct } from '@/lib/incident-view';
import { Untrusted } from '@/lib/untrusted';
import { useIncidentBundle } from '@/lib/useIncidentBundle';
import { useApi } from '@/lib/useApi';

function Claims({ incident, claims, empty, mark }: { incident: string; claims: Claim[]; empty: string; mark: string }) {
  if (claims.length === 0) return <p className="muted">{empty}</p>;
  return (
    <ul className="claims claims--marked">
      {claims.map((c, i) => (
        <li key={i}>
          <span className="claims__mark" aria-hidden="true">{mark}</span>
          <EpistemicBadge kind={claimEpistemic(c)} /> <Untrusted value={c.text} max={500} />{' '}
          <span className="muted">evidence: <EvidenceLinks incident={incident} ids={c.evidence} /></span>
        </li>
      ))}
    </ul>
  );
}

/** An alternative is only called rejected when the data says so. Otherwise we show what is known about it, which may be nothing. */
function Alternative({ incident, id, all }: { incident: string; id: string; all: Hypothesis[] }) {
  const other = all.find((h) => h.cause_id === id);
  const why = other?.contradicting[0];
  return (
    <li data-testid={`alt-${id}`}>
      <code><Untrusted value={id} max={80} /></code>{' '}
      {other ? <Tag kind={`hyp-${other.status}`}>{other.status}</Tag> : <span className="muted">not ranked</span>}
      {other && why ? <div className="muted">Counter-evidence: <Untrusted value={why.text} max={240} /> <EvidenceLinks incident={incident} ids={why.evidence} /></div>
        : <div className="muted">{other ? 'No counter-evidence recorded.' : 'No reason or evidence recorded for this alternative.'}</div>}
    </li>
  );
}

function HypothesisCard({ incident, h, all }: { incident: string; h: Hypothesis; all: Hypothesis[] }) {
  const basis = parseBasis(h);
  return (
    <article className={`card hyp hyp-${h.status}`} data-testid={`hyp-${h.rank}`}>
      <header>
        <h3>#{h.rank} <Untrusted value={h.cause_id} max={60} /></h3>
        <Tag kind={`hyp-${h.status}`}>{h.status}</Tag>
        <EpistemicBadge kind={hypothesisEpistemic(h)} />
        {h.service ? <span className="muted">service: <Untrusted value={h.service} max={40} /></span> : null}
      </header>
      <p><Untrusted value={h.description} max={500} /></p>
      <p className="ranking row">
        <span><span className="muted">Hypothesis ranking</span> <Meter value={h.confidence} label="ranking score" /></span>
        <span className="muted">Evidence coverage <strong className="mono">{pct(basis.coverage) ?? 'not reported'}</strong></span>
        <span className="muted">Independent signal types <strong className="mono">{basis.signalTypes ?? 'not reported'}</strong></span>
        <span className="muted">Contradictions <strong className="mono">{h.contradicting.length}</strong></span>
      </p>
      <p className="faint">(a ranking aid to order hypotheses; not a probability that this cause is true)</p>
      {h.confidence_basis && h.confidence_basis.length > 0 ? <p className="muted">basis: {h.confidence_basis.map((b, i) => <span key={i}>{i ? '; ' : ''}<Untrusted value={b} max={120} /></span>)}</p> : null}
      <h4>Supporting evidence</h4>
      <Claims incident={incident} claims={h.claims} empty="none" mark="✓" />
      <h4>Contradicting claims</h4>
      <Claims incident={incident} claims={h.contradicting} empty="None recorded. This does not prove that contradicting evidence does not exist." mark="✕" />
      <div className="split">
        <div><h4>Alternative hypotheses</h4>{h.alternatives.length ? <ul className="claims">{h.alternatives.map((a, i) => <Alternative key={i} incident={incident} id={a} all={all} />)}</ul> : <p className="muted">none listed</p>}</div>
        <div><h4>Unknowns</h4>{h.unknowns.length ? <ul className="claims">{h.unknowns.map((a, i) => <li key={i}><EpistemicBadge kind="UNKNOWN" /> <Untrusted value={a} max={200} /></li>)}</ul> : <p className="muted">none listed</p>}</div>
      </div>
    </article>
  );
}

export function DiagnosisBody({ incident, data, onTab }: { incident: string; data: Diagnosis; onTab?: (t: TabId) => void }) {
  const bundle = useIncidentBundle();
  const sorted = [...data.hypotheses].sort((a, b) => a.rank - b.rank);
  return (
    <>
      <p className="muted">
        Origin: <Tag kind={data.origin}>{data.origin === 'rule' ? 'deterministic rules' : 'LLM-assisted'}</Tag> · engine {data.engine_version ? <Untrusted value={data.engine_version} max={30} /> : 'n/a'} · generated {fmtTime(data.generated_at)}
      </p>
      <p className="note">Hypotheses are ranked, not proven. The “ranking score” orders candidates; it is not a calibrated probability. Only the verifier can confirm a cause.</p>
      {bundle && onTab ? <Panel title="Reasoning chain"><ReasoningChain b={bundle} onTab={onTab} /></Panel> : null}
      {data.recommended_action ? (
        <p><EpistemicBadge kind="RECOMMENDED" /> <code><Untrusted value={data.recommended_action.action_id} max={40} /> <Untrusted value={JSON.stringify(data.recommended_action.params)} max={200} /></code> <span className="muted">(a proposal; policy decides whether it can run)</span></p>
      ) : null}
      {sorted.map((h) => <HypothesisCard key={h.rank} incident={incident} h={h} all={sorted} />)}
    </>
  );
}

export function DiagnosisTab({ incident, onTab }: { incident: string; onTab?: (t: TabId) => void }) {
  const { data, error, loading, reload } = useApi(() => api.getDiagnosis(incident), [incident]);
  useLiveReload(reload, (e) => e.incident_id === incident);
  const keyRef = useRef<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const rediagnose = async () => {
    keyRef.current ??= newIdempotencyKey();
    try {
      await api.rediagnose(incident, keyRef.current);
      keyRef.current = null;
      setMsg('Re-diagnosis requested.');
      reload();
    } catch (e) {
      if (!(e instanceof ApiError && e.kind === 'network')) keyRef.current = null;
      setMsg(describeError(e));
    }
  };
  const notFound = error instanceof ApiError && error.kind === 'not_found';
  return (
    <section aria-label="Diagnosis">
      {notFound ? <EmptyState title="No diagnosis yet for this incident">Nothing on this tab is a conclusion until a diagnosis exists.</EmptyState> : <ErrorNote error={error} what="Diagnosis" />}
      {loading && !data ? <Skeleton label="diagnosis" lines={5} /> : null}
      {data ? (
        <>
          <DiagnosisBody incident={incident} data={data} onTab={onTab} />
          <p><button type="button" onClick={rediagnose}>Re-run diagnosis</button> {msg ? <span role="status">{msg}</span> : null}</p>
        </>
      ) : null}
    </section>
  );
}
