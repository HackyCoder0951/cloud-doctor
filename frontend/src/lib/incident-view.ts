// Pure view-model functions: API data in, what the operator should see out.
// Rules: nothing is invented. When the API does not report a value the function returns `undefined`
// (rendered as "not reported"), never a default that looks like a measurement. Text that comes from the
// API stays untrusted and is only ever rendered through <Untrusted>.
import type { Claim, Decision, Diagnosis, Evidence, Execution, Hypothesis, Incident, Plan, Remediation, Verification } from '@/api/types';

export const SEVERITY_ORDER = ['critical', 'high', 'medium', 'low'] as const;
const SEVERITY_WEIGHT: Record<string, number> = { critical: 4, high: 3, medium: 2, low: 1 };
export const isOpen = (i: Pick<Incident, 'state'>) => i.state !== 'recovered' && i.state !== 'closed';

export function topHypothesis(d: Diagnosis | undefined): Hypothesis | undefined {
  if (!d || d.hypotheses.length === 0) return undefined;
  return [...d.hypotheses].sort((a, b) => a.rank - b.rank)[0];
}

/** The incident has no title in the contract. The first symptom is the problem statement; the top hypothesis is the fallback. */
export function problemOf(i: Pick<Incident, 'symptoms'>, d?: Diagnosis): { text: string; derivedFrom: 'symptom' | 'hypothesis' | 'none' } {
  const s = i.symptoms.find((x) => x.trim().length > 0);
  if (s) return { text: s, derivedFrom: 'symptom' };
  const h = topHypothesis(d);
  if (h) return { text: h.description, derivedFrom: 'hypothesis' };
  return { text: 'No description reported', derivedFrom: 'none' };
}

/** `confidence_basis` is free text from the RCA engine, e.g. "evidence_coverage=0.73 (…)". Absent or malformed means not reported. */
export function parseBasis(h: Pick<Hypothesis, 'confidence_basis'> | undefined): { coverage?: number; signalTypes?: number } {
  const out: { coverage?: number; signalTypes?: number } = {};
  for (const b of h?.confidence_basis ?? []) {
    const cov = /^evidence_coverage=([0-9]*\.?[0-9]+)/.exec(b);
    if (cov && out.coverage === undefined) {
      const v = Number(cov[1]);
      if (Number.isFinite(v) && v >= 0 && v <= 1) out.coverage = v;
    }
    const sig = /^independent_signal_types=([0-9]+)/.exec(b);
    if (sig && out.signalTypes === undefined) out.signalTypes = Number(sig[1]);
  }
  return out;
}

export const pct = (v: number | undefined) => (v === undefined ? undefined : `${Math.round(v * 100)}%`);

// ----- epistemic status of a statement -----
export type Epistemic = 'OBSERVED' | 'INFERRED' | 'HYPOTHESIS' | 'RECOMMENDED' | 'CONFIRMED' | 'UNKNOWN';

export function claimEpistemic(c: Pick<Claim, 'type'>): Epistemic {
  switch (c.type) {
    case 'observation': return 'OBSERVED';
    case 'temporal_correlation':
    case 'inference': return 'INFERRED';
    default: return 'HYPOTHESIS';
  }
}

export function hypothesisEpistemic(h: Pick<Hypothesis, 'status'>): Epistemic {
  return h.status === 'confirmed' ? 'CONFIRMED' : 'HYPOTHESIS';
}

// ----- evidence -----
export type Trust = 'system_telemetry' | 'untrusted_text';
/** Log text can carry attacker-controlled content. Everything else is telemetry collected by Cloud Doctor itself. */
export function trustOf(e: Pick<Evidence, 'untrusted' | 'type'>): Trust {
  return e.untrusted || e.type === 'log' ? 'untrusted_text' : 'system_telemetry';
}

export type EvidenceRole = 'supporting' | 'contradicting' | 'context';
export function evidenceRole(id: string, h: Hypothesis | undefined): EvidenceRole {
  if (!h) return 'context';
  if (h.claims.some((c) => c.evidence.includes(id))) return 'supporting';
  if (h.contradicting.some((c) => c.evidence.includes(id))) return 'contradicting';
  return 'context';
}

/** What Cloud Doctor knows: observation claims behind the top hypothesis, de-duplicated, each with its evidence. */
export function knownFacts(h: Hypothesis | undefined): { text: string; evidence: string[] }[] {
  if (!h) return [];
  const seen = new Set<string>();
  const out: { text: string; evidence: string[] }[] = [];
  for (const c of [...h.claims, ...h.contradicting]) {
    if (c.type !== 'observation' || seen.has(c.text)) continue;
    seen.add(c.text);
    out.push({ text: c.text, evidence: [...c.evidence] });
  }
  return out;
}

export const unknownFacts = (h: Hypothesis | undefined): string[] => [...new Set(h?.unknowns ?? [])];

// ----- remediation state -----
export function awaitingApproval(p: Plan, decisions: Decision[], executions: Execution[]): boolean {
  const mine = decisions.filter((d) => d.plan_id === p.plan_id);
  const latest = mine[mine.length - 1];
  return p.risk_class === 'medium' && latest?.final === 'allow_with_approval' && !executions.some((x) => x.plan_id === p.plan_id);
}

export function pendingApprovals(r: Remediation | undefined): Plan[] {
  if (!r) return [];
  return r.plans.filter((p) => awaitingApproval(p, r.decisions, r.executions));
}

/** A human is needed when a plan waits for approval, the incident was escalated, or the circuit breaker stopped automation. */
export function needsHuman(i: Pick<Incident, 'state'>, r: Remediation | undefined): boolean {
  if (!isOpen(i)) return false;
  return i.state === 'escalated' || pendingApprovals(r).length > 0 || r?.circuit_breaker === 'open';
}

// ----- lifecycle -----
export type StageId = 'detected' | 'diagnosed' | 'acting' | 'verified';
export type StageStatus = 'done' | 'current' | 'pending' | 'blocked';
export interface Stage { id: StageId; label: string; status: StageStatus; detail: string }

export function lifecycle(i: Incident, d: Diagnosis | undefined, r: Remediation | undefined, v: Verification[] | undefined): Stage[] {
  const diagnosed = !!topHypothesis(d);
  const planned = (r?.plans.length ?? 0) > 0;
  const executed = (r?.executions.length ?? 0) > 0;
  const lastV = v && v.length > 0 ? v[v.length - 1] : undefined;
  const recovered = lastV?.verdict === 'recovered' || i.state === 'recovered' || i.state === 'closed';
  const waiting = pendingApprovals(r).length > 0;
  const blocked = i.state === 'escalated' || r?.circuit_breaker === 'open';

  const detected: Stage = { id: 'detected', label: 'Detected', status: 'done', detail: `Opened ${i.opened_at}. Severity ${i.severity}. ${i.symptoms.length} symptom${i.symptoms.length === 1 ? '' : 's'} recorded.` };
  const diag: Stage = diagnosed
    ? { id: 'diagnosed', label: 'Diagnosed', status: 'done', detail: `${d?.hypotheses.length ?? 0} ranked hypotheses from ${d?.origin === 'rule' ? 'rule-based analysis' : 'LLM-assisted analysis'}. A ranking is not a confirmed cause.` }
    : { id: 'diagnosed', label: 'Diagnosed', status: i.state === 'detected' || i.state === 'investigating' ? 'current' : 'pending', detail: 'No diagnosis has been produced yet.' };
  let acting: Stage;
  if (recovered && executed) acting = { id: 'acting', label: 'Acting', status: 'done', detail: `${r?.executions.length ?? 0} execution${r?.executions.length === 1 ? '' : 's'} recorded.` };
  else if (blocked) acting = { id: 'acting', label: 'Acting', status: 'blocked', detail: 'Automation stopped: the incident was escalated or the circuit breaker is open. A human must decide.' };
  else if (waiting) acting = { id: 'acting', label: 'Acting', status: 'current', detail: 'A plan is waiting for operator approval. Nothing runs until it is approved and policy re-checks it.' };
  else if (executed) acting = { id: 'acting', label: 'Acting', status: 'current', detail: 'An action ran; verification is pending.' };
  else if (planned) acting = { id: 'acting', label: 'Acting', status: 'current', detail: 'A plan exists and is being evaluated by policy.' };
  else acting = { id: 'acting', label: 'Acting', status: diagnosed ? 'current' : 'pending', detail: diagnosed ? 'No remediation plan yet.' : 'Waiting for a diagnosis.' };
  const verified: Stage = recovered
    ? { id: 'verified', label: 'Verified', status: 'done', detail: lastV ? `Verdict ${lastV.verdict} over the window ${lastV.window_start} to ${lastV.window_end}.` : 'Incident is recovered.' }
    : lastV
      ? { id: 'verified', label: 'Verified', status: lastV.verdict === 'failed' || lastV.verdict === 'regression' || lastV.verdict === 'relapse' ? 'blocked' : 'current', detail: `Latest verdict: ${lastV.verdict}. Recovery is not claimed until every check passes.` }
      : { id: 'verified', label: 'Verified', status: 'pending', detail: 'No verification has run. Without one the incident is not considered recovered.' };
  return [detected, diag, acting, verified];
}

// ----- queue ordering and filtering -----
export type QueueFilter = 'all' | 'active' | 'needs_human' | 'recovering' | 'closed';
export const QUEUE_FILTERS: { id: QueueFilter; label: string }[] = [
  { id: 'all', label: 'All' }, { id: 'active', label: 'Active' }, { id: 'needs_human', label: 'Needs human' }, { id: 'recovering', label: 'Recovering' }, { id: 'closed', label: 'Closed' },
];

export function queuePhase(i: Pick<Incident, 'state'>, human: boolean): 'needs_human' | 'recovering' | 'active' | 'closed' {
  if (!isOpen(i)) return 'closed';
  if (human) return 'needs_human';
  if (i.state === 'remediating' || i.state === 'verifying') return 'recovering';
  return 'active';
}

export function matchesFilter(f: QueueFilter, i: Pick<Incident, 'state'>, human: boolean): boolean {
  if (f === 'all') return true;
  const p = queuePhase(i, human);
  return f === 'active' ? p === 'active' || p === 'needs_human' || p === 'recovering' : p === f;
}

export function attentionScore(i: Pick<Incident, 'state' | 'severity'>, human: boolean): number {
  return (human ? 100 : 0) + (SEVERITY_WEIGHT[i.severity] ?? 0) * 10 + (i.state === 'escalated' ? 5 : 0);
}

export const PHASE_LABEL = { needs_human: 'Needs human', recovering: 'Recovering', active: 'Active', closed: 'Closed' } as const;
