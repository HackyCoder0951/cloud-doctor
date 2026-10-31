'use client';
// Incident header, lifecycle stepper and action rail. All values are derived in lib/incident-view.ts.
import Link from 'next/link';
import { useState } from 'react';
import { fmtTime } from '@/components/common';
import { IncidentStateBadge, Tag, VerdictBadge } from '@/components/badges';
import { Pill, SeverityBadge, type Tone } from '@/components/ui';
import { lifecycle, needsHuman, pendingApprovals, PHASE_LABEL, problemOf, queuePhase, topHypothesis, type Stage, type StageStatus } from '@/lib/incident-view';
import { isServiceName, Untrusted } from '@/lib/untrusted';
import type { IncidentBundle } from '@/lib/useIncidentBundle';

const STAGE_GLYPH: Record<StageStatus, string> = { done: '✓', current: '●', pending: '○', blocked: '✕' };
const STAGE_LABEL: Record<StageStatus, string> = { done: 'done', current: 'in progress', pending: 'not started', blocked: 'blocked' };

export function Stepper({ stages }: { stages: Stage[] }) {
  const initial = stages.find((s) => s.status === 'blocked' || s.status === 'current')?.id ?? stages[stages.length - 1]?.id;
  const [open, setOpen] = useState<string | undefined>(initial);
  const shown = stages.find((s) => s.id === open);
  return (
    <div className="stepper" data-testid="lifecycle">
      <ol className="stepper__list" aria-label="Incident lifecycle">
        {stages.map((s, i) => (
          <li key={s.id} className="stepper__item" data-status={s.status}>
            <button type="button" className="stepper__button" aria-expanded={open === s.id} aria-controls="stage-detail" onClick={() => setOpen(open === s.id ? undefined : s.id)}>
              <span className="stepper__glyph" aria-hidden="true">{STAGE_GLYPH[s.status]}</span>
              <span className="stepper__label">{s.label}</span>
              <span className="sr-only"> ({STAGE_LABEL[s.status]})</span>
            </button>
            {i < stages.length - 1 ? <span className="stepper__arrow" aria-hidden="true">→</span> : null}
          </li>
        ))}
      </ol>
      <p id="stage-detail" className="stepper__detail" aria-live="polite">{shown ? <><strong>{shown.label}: {STAGE_LABEL[shown.status]}.</strong> <Untrusted value={shown.detail} max={400} /></> : <span className="muted">Select a stage to see what happened.</span>}</p>
    </div>
  );
}

export function IncidentHeader({ b }: { b: IncidentBundle }) {
  const i = b.incident;
  if (!i) return null;
  const d = b.diagnosis ?? undefined;
  const human = needsHuman(i, b.remediation);
  const phase = queuePhase(i, human);
  const problem = problemOf(i, d);
  const stages = lifecycle(i, d, b.remediation, b.verification);
  const tone: Tone = phase === 'needs_human' ? 'warn' : phase === 'closed' ? 'ok' : 'info';
  return (
    <section className="ihead" aria-label="Incident summary" data-severity={i.severity}>
      <div className="row">
        <span className="mono ihead__id">{i.incident_id}</span>
        <SeverityBadge severity={i.severity} />
        <IncidentStateBadge state={i.state} />
        <Pill tone={tone} glyph={phase === 'needs_human' ? '!' : '●'} testId="phase">{PHASE_LABEL[phase].toUpperCase()}</Pill>
        <span className="spacer" />
        <span className="muted mono">opened {fmtTime(i.opened_at)}{i.closed_at ? ` · closed ${fmtTime(i.closed_at)}` : ''}</span>
      </div>
      <h1 className="ihead__title"><Untrusted value={problem.text} max={200} /></h1>
      {problem.derivedFrom !== 'none' ? <p className="faint ihead__derived">Title taken from the {problem.derivedFrom === 'symptom' ? 'first reported symptom' : 'top hypothesis'}; the API has no incident title field.</p> : null}
      <p className="row">
        <span>Services:</span>
        {i.services.map((s) => (isServiceName(s) ? <Link key={s} className="svc-chip" href={`/services/view/?name=${s}`}>{s}</Link> : <Untrusted key={s} value={s} max={40} />))}
        {i.outcome ? <span className="muted">outcome: <strong>{i.outcome}</strong></span> : null}
        <span className="muted">root cause confirmed: <strong>{i.root_cause_confirmed ? 'yes' : 'no'}</strong></span>
        {i.run_id ? <span className="muted">harness run: <Untrusted value={i.run_id} max={60} /></span> : null}
      </p>
      <Stepper stages={stages} />
    </section>
  );
}

export function ActionRail({ b, onTab }: { b: IncidentBundle; onTab: (t: 'remediation' | 'verification' | 'diagnosis') => void }) {
  const i = b.incident;
  if (!i) return null;
  const r = b.remediation;
  const d = b.diagnosis ?? undefined;
  const pending = pendingApprovals(r);
  const lastDecision = r?.decisions[r.decisions.length - 1];
  const lastVer = b.verification && b.verification.length > 0 ? b.verification[b.verification.length - 1] : undefined;
  const top = topHypothesis(d);
  return (
    <aside className="rail" aria-label="Action" data-testid="action-rail">
      <h2 className="rail__title">Action</h2>
      <div className="rail__block">
        <h4>Next step</h4>
        {pending.length > 0 ? (
          <>
            <p><strong>Approval required</strong>: <code>{pending[0]?.action_id}</code> <Tag kind={`risk-${pending[0]?.risk_class}`}>risk: {pending[0]?.risk_class}</Tag></p>
            <p className="muted">Nothing runs until an operator approves and policy re-checks the plan.</p>
            <button type="button" onClick={() => onTab('remediation')}>Review plan {pending[0]?.plan_id}</button>
          </>
        ) : i.state === 'escalated' || r?.circuit_breaker === 'open' ? (
          <p><strong>Escalated.</strong> <span className="muted">Automation is stopped. A human must decide.</span></p>
        ) : (r?.executions.length ?? 0) > 0 && !lastVer ? (
          <p className="muted">An action ran. Waiting for verification.</p>
        ) : d?.recommended_action ? (
          <p><span className="muted">Recommended (a proposal, policy decides):</span> <code><Untrusted value={d.recommended_action.action_id} max={40} /></code></p>
        ) : top ? (
          <p className="muted">No action proposed for this diagnosis.</p>
        ) : (
          <p className="muted">Waiting for a diagnosis.</p>
        )}
      </div>
      <div className="rail__block">
        <h4>Policy</h4>
        {lastDecision ? (
          <p><Tag kind={`dec-${lastDecision.final}`}>{lastDecision.final}</Tag> <span className="muted">layer 1 {lastDecision.l1.result}{lastDecision.l2 ? `, layer 2 ${lastDecision.l2.result}` : ', layer 2 not evaluated'}</span></p>
        ) : <p className="muted">No policy decision recorded yet.</p>}
      </div>
      <div className="rail__block">
        <h4>Verification</h4>
        {lastVer ? <p><VerdictBadge verdict={lastVer.verdict} /> <button type="button" className="ghost" onClick={() => onTab('verification')}>Details</button></p> : <p className="muted">Not run. Without it the incident is not considered recovered.</p>}
      </div>
      <div className="rail__block">
        <h4>Environment</h4>
        <p><Pill tone="warn" glyph="●">SANDBOX</Pill></p>
        <p className="faint">Actions run only against sandbox-labelled containers.</p>
      </div>
    </aside>
  );
}
