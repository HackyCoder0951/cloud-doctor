import { describe, expect, it } from 'vitest';
import type { Decision, Diagnosis, Execution, Hypothesis, Incident, Plan, Remediation, Verification } from '../src/api/types';
import {
  attentionScore, awaitingApproval, claimEpistemic, evidenceRole, knownFacts, lifecycle, matchesFilter, needsHuman, parseBasis, pct, problemOf, topHypothesis, trustOf, unknownFacts,
} from '../src/lib/incident-view';

const inc = (over: Partial<Incident> = {}): Incident => ({ incident_id: 'INC-0003', state: 'diagnosed', opened_at: '2026-11-01T19:10:51Z', severity: 'critical', services: ['api', 'app-db'], symptoms: ['app-db is out of connections'], ...over }) as Incident;
const hyp = (over: Partial<Hypothesis> = {}): Hypothesis => ({
  rank: 1, cause_id: 'app_db_connection_exhaustion', description: 'connection limit reached', confidence: 0.44, status: 'supported',
  confidence_basis: ['evidence_coverage=0.73 (3.0/4.1 signal weight)', 'independent_signal_types=1 (metric) factor=0.60'],
  claims: [{ text: 'db refused connections', type: 'observation', evidence: ['EV-034'] }, { text: 'api failed after db', type: 'temporal_correlation', evidence: ['EV-015'] }],
  contradicting: [{ text: 'database process is up', type: 'observation', evidence: ['EV-028'] }],
  alternatives: ['app_db_unavailable'], unknowns: ['which client holds the connections', 'which client holds the connections', 'whether a deploy caused it'], ...over,
}) as Hypothesis;
const diag = (hs: Hypothesis[] = [hyp()]): Diagnosis => ({ incident_id: 'INC-0003', generated_at: '2026-11-01T19:11:00Z', origin: 'rule', hypotheses: hs }) as Diagnosis;
const plan = (id = 'PL-0001', risk: Plan['risk_class'] = 'medium'): Plan => ({ plan_id: id, incident_id: 'INC-0003', action_id: 'restart_service', params: { service: 'worker' }, risk_class: risk, origin: 'rule', evidence_refs: ['EV-034'], rationale: 'r', created_at: 't', plan_hash: 'a'.repeat(64) }) as Plan;
const dec = (planId: string, final: Decision['final']): Decision => ({ decision_id: 'DEC-0001', plan_id: planId, plan_hash: 'a'.repeat(64), final, l1: { result: 'pass', rule_ids: [] }, reasons: [], decided_at: 't', invariants_version: '1' }) as Decision;
const rem = (over: Partial<Remediation> = {}): Remediation => ({ plans: [], decisions: [], executions: [], ...over });

describe('problemOf', () => {
  it('uses the first symptom, then the top hypothesis, then says nothing was reported', () => {
    expect(problemOf(inc(), diag())).toEqual({ text: 'app-db is out of connections', derivedFrom: 'symptom' });
    expect(problemOf(inc({ symptoms: ['  '] }), diag())).toEqual({ text: 'connection limit reached', derivedFrom: 'hypothesis' });
    expect(problemOf(inc({ symptoms: [] }), undefined)).toEqual({ text: 'No description reported', derivedFrom: 'none' });
  });
});

describe('parseBasis', () => {
  it('reads coverage and signal types from the RCA engine text', () => {
    expect(parseBasis(hyp())).toEqual({ coverage: 0.73, signalTypes: 1 });
    expect(pct(0.73)).toBe('73%');
  });
  it('reports nothing when the basis is absent or malformed (never a default number)', () => {
    expect(parseBasis(hyp({ confidence_basis: undefined }))).toEqual({});
    expect(parseBasis(hyp({ confidence_basis: ['evidence_coverage=banana', 'evidence_coverage=7'] }))).toEqual({});
    expect(parseBasis(undefined)).toEqual({});
    expect(pct(undefined)).toBeUndefined();
  });
});

describe('evidence and claims', () => {
  it('orders hypotheses by rank and picks the lowest rank', () => {
    expect(topHypothesis(diag([hyp({ rank: 3, cause_id: 'c' }), hyp({ rank: 1, cause_id: 'a' })]))?.cause_id).toBe('a');
    expect(topHypothesis(diag([]))).toBeUndefined();
    expect(topHypothesis(undefined)).toBeUndefined();
  });
  it('labels claims honestly: an observation is OBSERVED, a temporal correlation is only INFERRED', () => {
    expect(claimEpistemic({ type: 'observation' })).toBe('OBSERVED');
    expect(claimEpistemic({ type: 'temporal_correlation' })).toBe('INFERRED');
    expect(claimEpistemic({ type: 'hypothesis' })).toBe('HYPOTHESIS');
  });
  it('marks log evidence and anything flagged untrusted as untrusted text', () => {
    expect(trustOf({ untrusted: false, type: 'metric' })).toBe('system_telemetry');
    expect(trustOf({ untrusted: true, type: 'metric' })).toBe('untrusted_text');
    expect(trustOf({ untrusted: false, type: 'log' })).toBe('untrusted_text');
  });
  it('assigns evidence a role relative to the top hypothesis', () => {
    const h = hyp();
    expect(evidenceRole('EV-034', h)).toBe('supporting');
    expect(evidenceRole('EV-028', h)).toBe('contradicting');
    expect(evidenceRole('EV-999', h)).toBe('context');
    expect(evidenceRole('EV-034', undefined)).toBe('context');
  });
  it('knows only observations, and de-duplicates unknowns', () => {
    expect(knownFacts(hyp()).map((k) => k.text)).toEqual(['db refused connections', 'database process is up']);
    expect(unknownFacts(hyp())).toEqual(['which client holds the connections', 'whether a deploy caused it']);
    expect(knownFacts(undefined)).toEqual([]);
  });
});

describe('needsHuman and approvals', () => {
  const p = plan();
  it('a medium plan with allow_with_approval and no execution awaits approval', () => {
    expect(awaitingApproval(p, [dec('PL-0001', 'allow_with_approval')], [])).toBe(true);
    expect(awaitingApproval(p, [dec('PL-0001', 'allow')], [])).toBe(false);
    expect(awaitingApproval(p, [dec('PL-0001', 'allow_with_approval')], [{ plan_id: 'PL-0001' } as Execution])).toBe(false);
    expect(awaitingApproval(plan('PL-0002', 'low'), [dec('PL-0002', 'allow_with_approval')], [])).toBe(false);
  });
  it('needs a human when approval is pending, the incident is escalated or the breaker is open, but never for a closed incident', () => {
    expect(needsHuman(inc(), rem({ plans: [p], decisions: [dec('PL-0001', 'allow_with_approval')] }))).toBe(true);
    expect(needsHuman(inc({ state: 'escalated' }), rem())).toBe(true);
    expect(needsHuman(inc(), rem({ circuit_breaker: 'open' }))).toBe(true);
    expect(needsHuman(inc(), rem())).toBe(false);
    expect(needsHuman(inc({ state: 'closed', }), rem({ circuit_breaker: 'open' }))).toBe(false);
    expect(needsHuman(inc(), undefined)).toBe(false);
  });
});

describe('lifecycle', () => {
  const v = (verdict: Verification['verdict']): Verification => ({ incident_id: 'INC-0003', execution_id: 'EX-0001', verdict, window_start: 'a', window_end: 'b', checks: [] }) as Verification;
  const statuses = (s: ReturnType<typeof lifecycle>) => s.map((x) => `${x.id}:${x.status}`).join(' ');
  it('a fresh incident is detected with nothing else claimed', () => {
    expect(statuses(lifecycle(inc({ state: 'detected' }), undefined, undefined, undefined))).toBe('detected:done diagnosed:current acting:pending verified:pending');
  });
  it('waiting for approval is the current acting step', () => {
    const r = rem({ plans: [plan()], decisions: [dec('PL-0001', 'allow_with_approval')] });
    expect(statuses(lifecycle(inc(), diag(), r, undefined))).toBe('detected:done diagnosed:done acting:current verified:pending');
  });
  it('an escalated incident is blocked, not silently pending', () => {
    expect(lifecycle(inc({ state: 'escalated' }), diag(), rem(), undefined)[2]?.status).toBe('blocked');
  });
  it('is verified only on a recovered verdict or a recovered state', () => {
    const r = rem({ plans: [plan('PL-0001', 'low')], executions: [{ plan_id: 'PL-0001' } as Execution] });
    expect(lifecycle(inc({ state: 'verifying' }), diag(), r, [v('partial')])[3]?.status).toBe('current');
    expect(lifecycle(inc({ state: 'verifying' }), diag(), r, [v('failed')])[3]?.status).toBe('blocked');
    expect(statuses(lifecycle(inc({ state: 'recovered' }), diag(), r, [v('recovered')]))).toBe('detected:done diagnosed:done acting:done verified:done');
  });
});

describe('queue', () => {
  it('filters by phase and ranks a human-needed incident above a quieter critical one', () => {
    expect(matchesFilter('needs_human', inc(), true)).toBe(true);
    expect(matchesFilter('active', inc(), true)).toBe(true);
    expect(matchesFilter('closed', inc({ state: 'closed' }), false)).toBe(true);
    expect(matchesFilter('recovering', inc({ state: 'verifying' }), false)).toBe(true);
    expect(attentionScore(inc({ severity: 'medium' }), true)).toBeGreaterThan(attentionScore(inc({ severity: 'critical' }), false));
  });
});
