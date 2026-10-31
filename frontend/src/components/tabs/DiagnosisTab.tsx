'use client';
import { useRef, useState } from 'react';
import { api, ApiError, describeError, newIdempotencyKey } from '@/api/client';
import type { Claim, Hypothesis } from '@/api/types';
import { ErrorNote, fmtTime, Loading } from '@/components/common';
import { EvidenceLinks } from '@/components/EvidenceLink';
import { useLiveReload } from '@/components/Live';
import { Tag } from '@/components/badges';
import { Untrusted } from '@/lib/untrusted';
import { useApi } from '@/lib/useApi';

function Claims({ incident, claims, empty }: { incident: string; claims: Claim[]; empty: string }) {
  if (claims.length === 0) return <p className="muted">{empty}</p>;
  return (
    <ul className="claims">
      {claims.map((c, i) => (
        <li key={i}>
          <Tag kind={c.type}>{c.type.replace('_', ' ')}</Tag> <Untrusted value={c.text} max={500} />{' '}
          <span className="muted">evidence: <EvidenceLinks incident={incident} ids={c.evidence} /></span>
        </li>
      ))}
    </ul>
  );
}

function HypothesisCard({ incident, h }: { incident: string; h: Hypothesis }) {
  return (
    <article className={`card hyp hyp-${h.status}`} data-testid={`hyp-${h.rank}`}>
      <header>
        <h3>#{h.rank} <Untrusted value={h.cause_id} max={60} /></h3>
        <Tag kind={`hyp-${h.status}`}>{h.status}</Tag>
        {h.service ? <span className="muted">service: <Untrusted value={h.service} max={40} /></span> : null}
      </header>
      <p><Untrusted value={h.description} max={500} /></p>
      <p className="ranking">
        <label>ranking score <meter min={0} max={1} value={h.confidence} aria-label="ranking score" /></label> <strong>{h.confidence.toFixed(2)}</strong>{' '}
        <span className="muted">(a ranking aid to order hypotheses; not a probability that this cause is true)</span>
      </p>
      {h.confidence_basis && h.confidence_basis.length > 0 ? <p className="muted">basis: {h.confidence_basis.map((b, i) => <span key={i}>{i ? '; ' : ''}<Untrusted value={b} max={120} /></span>)}</p> : null}
      <h4>Supporting claims</h4>
      <Claims incident={incident} claims={h.claims} empty="none" />
      <h4>Contradicting claims</h4>
      <Claims incident={incident} claims={h.contradicting} empty="No contradicting evidence recorded (this is not proof there is none)." />
      <div className="two">
        <div><h4>Alternatives</h4>{h.alternatives.length ? <ul>{h.alternatives.map((a, i) => <li key={i}><Untrusted value={a} max={80} /></li>)}</ul> : <p className="muted">none listed</p>}</div>
        <div><h4>Unknowns</h4>{h.unknowns.length ? <ul>{h.unknowns.map((a, i) => <li key={i}><Untrusted value={a} max={200} /></li>)}</ul> : <p className="muted">none listed</p>}</div>
      </div>
    </article>
  );
}

export function DiagnosisTab({ incident }: { incident: string }) {
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
      {notFound ? <p className="muted">No diagnosis yet for this incident.</p> : <ErrorNote error={error} what="Diagnosis" />}
      {loading && !data ? <Loading what="diagnosis" /> : null}
      {data ? (
        <>
          <p className="muted">
            Origin: <Tag kind={data.origin}>{data.origin === 'rule' ? 'deterministic rules' : 'LLM-assisted'}</Tag> · engine {data.engine_version ? <Untrusted value={data.engine_version} max={30} /> : 'n/a'} · generated {fmtTime(data.generated_at)}
          </p>
          <p className="note">Hypotheses are ranked, not proven. The “ranking score” orders candidates; it is not a calibrated probability. Only the verifier can confirm a cause.</p>
          {data.recommended_action ? (
            <p>Recommended action: <code><Untrusted value={data.recommended_action.action_id} max={40} /> <Untrusted value={JSON.stringify(data.recommended_action.params)} max={200} /></code> <span className="muted">(a proposal; policy decides whether it can run)</span></p>
          ) : null}
          {[...data.hypotheses].sort((a, b) => a.rank - b.rank).map((h) => <HypothesisCard key={h.rank} incident={incident} h={h} />)}
          <p><button type="button" onClick={rediagnose}>Re-run diagnosis</button> {msg ? <span role="status">{msg}</span> : null}</p>
        </>
      ) : null}
    </section>
  );
}
