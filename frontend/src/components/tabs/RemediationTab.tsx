'use client';
import { useRef, useState } from 'react';
import { api, ApiError, describeError, newIdempotencyKey } from '@/api/client';
import type { Decision, Execution, Plan } from '@/api/types';
import { ErrorNote, fmtTime, Loading } from '@/components/common';
import { EvidenceLinks } from '@/components/EvidenceLink';
import { useLiveReload } from '@/components/Live';
import { Tag } from '@/components/badges';
import { Untrusted } from '@/lib/untrusted';
import { useApi } from '@/lib/useApi';

export function DecisionView({ d }: { d: Decision }) {
  return (
    <div className="decision" data-testid={`dec-${d.decision_id}`}>
      <p>
        <strong>{d.decision_id}</strong> final: <Tag kind={`dec-${d.final}`}>{d.final}</Tag> <span className="muted">decided {fmtTime(d.decided_at)} · invariants {d.invariants_version}</span>
      </p>
      <p>
        Layer 1 (invariants, mandatory): <Tag kind={`l-${d.l1.result}`}>{d.l1.result}</Tag> <span className="muted">rules: {d.l1.rule_ids.join(', ') || 'none'}</span>
      </p>
      <p>
        Layer 2 (client policy, can only tighten):{' '}
        {d.l2 ? (
          <>
            <Tag kind={`dec-${d.l2.result}`}>{d.l2.result}</Tag> <span className="muted">rules: {d.l2.rule_ids.join(', ') || 'none'}{d.l2.bundle_revision ? ` · bundle ${d.l2.bundle_revision}` : ''}{d.l2.bundle_signed === false ? ' · UNSIGNED bundle' : d.l2.bundle_signed ? ' · signed' : ''}</span>
          </>
        ) : <span className="muted">not evaluated (a missing Layer 2 result is never an allow)</span>}
      </p>
      <ul className="reasons">{d.reasons.map((r, i) => <li key={i}><Untrusted value={r} max={300} /></li>)}</ul>
    </div>
  );
}

export function ExecutionView({ x }: { x: Execution }) {
  const argv = x.executed_argv ?? [];
  return (
    <div className={`execution ex-${x.result}`} data-testid={`exec-${x.execution_id}`}>
      <p>
        <strong>{x.execution_id}</strong> <Tag kind={`ex-${x.result}`}>{x.result}</Tag>{' '}
        <span className="muted">{fmtTime(x.started_at)} → {fmtTime(x.ended_at)} · idempotency key <code><Untrusted value={x.idempotency_key} max={64} /></code></span>
      </p>
      <p>
        Exact argv (never a shell string):{' '}
        {argv.length === 0 ? <em>no command executed</em> : (
          <code className="argv" data-testid="argv">{argv.map((a, i) => <span key={i} className="arg"><Untrusted value={a} max={120} /></span>)}</code>
        )}
      </p>
      {x.refusal_rule_ids && x.refusal_rule_ids.length > 0 ? <p>Refused by: {x.refusal_rule_ids.join(', ')}</p> : null}
      {x.detail ? <p className="muted"><Untrusted value={x.detail} max={300} /></p> : null}
    </div>
  );
}

export function ApprovalPanel({ incident, plan, onDone }: { incident: string; plan: Plan; onDone: () => void }) {
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  // One key per user action: kept after a network failure (the outcome is unknown, so a retry must be
  // the same operation) and discarded once the API gave a definitive answer.
  const keyRef = useRef<string | null>(null);
  const valid = reason.trim().length >= 3 && reason.length <= 300;

  const run = async (kind: 'approve' | 'reject') => {
    if (!valid) return;
    setBusy(true);
    setMsg(null);
    keyRef.current ??= newIdempotencyKey();
    try {
      if (kind === 'approve') {
        const d = await api.approvePlan(incident, plan.plan_id, { plan_hash: plan.plan_hash, reason: reason.trim() }, keyRef.current);
        setMsg({ ok: true, text: `Approved. Decision ${d.decision_id}: ${d.final}. Policy is re-evaluated at execution.` });
      } else {
        await api.rejectPlan(incident, plan.plan_id, { reason: reason.trim() }, keyRef.current);
        setMsg({ ok: true, text: 'Rejected.' });
      }
      keyRef.current = null;
      onDone();
    } catch (e) {
      if (!(e instanceof ApiError && e.kind === 'network')) keyRef.current = null;
      setMsg({ ok: false, text: describeError(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="approval card" onSubmit={(e) => e.preventDefault()} aria-label={`Approval for ${plan.plan_id}`}>
      <h4>Operator decision required (medium risk)</h4>
      <p className="muted">Your approval is bound to this exact plan hash; if the plan changes, the API rejects it. The API checks your role and re-runs policy before anything executes.</p>
      <p>plan_hash: <code data-testid="plan-hash">{plan.plan_hash}</code></p>
      <label>Reason (3–300 characters, recorded in the audit log)
        <textarea value={reason} onChange={(e) => { setReason(e.target.value); }} maxLength={300} rows={2} />
      </label>
      <p className="row">
        <button type="button" disabled={!valid || busy} onClick={() => run('approve')}>Approve plan {plan.plan_id}</button>
        <button type="button" className="secondary" disabled={!valid || busy} onClick={() => run('reject')}>Reject plan {plan.plan_id}</button>
      </p>
      {msg ? <p role={msg.ok ? 'status' : 'alert'} className={msg.ok ? 'ok' : 'error'}>{msg.text}</p> : null}
    </form>
  );
}

export function RemediationTab({ incident }: { incident: string }) {
  const { data, error, loading, reload } = useApi(() => api.getRemediation(incident), [incident]);
  useLiveReload(reload, (e) => e.incident_id === incident);
  return (
    <section aria-label="Remediation">
      <ErrorNote error={error} what="Remediation" />
      {loading && !data ? <Loading what="remediation" /> : null}
      {data ? (
        <>
          <p className="row" data-testid="budget">
            Circuit breaker: <Tag kind={`cb-${data.circuit_breaker ?? 'unknown'}`}>{data.circuit_breaker ?? 'unknown'}</Tag>
            Attempts remaining: <strong>{data.attempts_remaining ?? 'unknown'}</strong>
            {data.circuit_breaker === 'open' ? <span className="error">Automatic remediation is stopped for this incident.</span> : null}
          </p>
          {data.plans.length === 0 ? <p className="muted">No remediation plans yet. Plans are created by the system, never by the UI.</p> : null}
          {data.plans.map((p) => {
            const decisions = data.decisions.filter((d) => d.plan_id === p.plan_id);
            const executions = data.executions.filter((x) => x.plan_id === p.plan_id);
            const latest = decisions[decisions.length - 1];
            const awaiting = p.risk_class === 'medium' && latest?.final === 'allow_with_approval' && executions.length === 0;
            return (
              <article key={p.plan_id} className="card plan" data-testid={`plan-${p.plan_id}`}>
                <header>
                  <h3>{p.plan_id} <code>{p.action_id}</code></h3>
                  <Tag kind={`risk-${p.risk_class}`}>risk: {p.risk_class}</Tag> <Tag kind="origin">origin: {p.origin}</Tag>
                </header>
                <p>Parameters: <code>{Object.entries(p.params).map(([k, v]) => `${k}=${String(v)}`).join(' ') || 'none'}</code></p>
                <p><Untrusted value={p.rationale} max={500} /></p>
                <p className="muted">Evidence: <EvidenceLinks incident={incident} ids={p.evidence_refs} /> · created {fmtTime(p.created_at)} · hash <code>{p.plan_hash}</code></p>
                <h4>Policy decisions</h4>
                {decisions.length === 0 ? <p className="muted">No decision recorded yet.</p> : decisions.map((d) => <DecisionView key={d.decision_id} d={d} />)}
                <h4>Executions</h4>
                {executions.length === 0 ? <p className="muted">Not executed.</p> : executions.map((x) => <ExecutionView key={x.execution_id} x={x} />)}
                {awaiting ? <ApprovalPanel incident={incident} plan={p} onDone={reload} /> : null}
              </article>
            );
          })}
        </>
      ) : null}
    </section>
  );
}
