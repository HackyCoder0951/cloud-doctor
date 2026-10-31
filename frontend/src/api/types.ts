// Convenience aliases over the generated schema (src/api/schema.d.ts, from contracts/openapi.yaml).
// openapi-typescript renders a bare `type: object` as Record<string, never>; the free-form
// payload/data objects are re-typed here as Record<string, unknown> (they are untrusted JSON).
import type { components } from './schema';

type S = components['schemas'];

export type HealthState = S['health_state'];
export type MissingSignalState = S['missing_signal_state'];
export type IncidentState = S['incident_state'];
export type EvidenceStatus = S['evidence_status'];
export type Verdict = S['verdict'];
export type RiskClass = S['risk_class'];
export type ServiceHealth = S['ServiceHealth'];
export type Topology = S['Topology'];
export type Incident = S['incident'];
export type TimelineEvent = S['timeline_event'];
export type Evidence = Omit<S['evidence'], 'payload'> & { payload: Record<string, unknown> };
export type Claim = S['claim'];
export type Diagnosis = Omit<S['diagnosis'], '$defs' | 'recommended_action'> & {
  recommended_action?: { action_id: S['action_id']; params: Record<string, unknown> };
};
export type Hypothesis = Diagnosis['hypotheses'][number];
export type Plan = S['plan'];
export type Decision = S['decision'];
export type Execution = S['execution'];
export type Verification = S['verification'];
export type Report = Omit<S['report'], 'diagnosis'> & { diagnosis: Diagnosis };
export type AuditEvent = Omit<S['audit_event'], 'detail'> & { detail: Record<string, unknown> };
export type StreamEvent = Omit<S['StreamEvent'], 'data'> & { data?: Record<string, unknown> };
export type StreamEventType = StreamEvent['type'];
export type ApiErrorBody = S['Error'];

export interface Remediation {
  plans: Plan[];
  decisions: Decision[];
  executions: Execution[];
  circuit_breaker?: 'closed' | 'open' | 'half_open';
  attempts_remaining?: number;
}

export interface MetricSeries {
  service: string;
  name: string;
  status: EvidenceStatus;
  points: { t: string; v: number }[];
}

export interface LogResponse {
  service: string;
  status: EvidenceStatus;
  lines: { t: string; line: string; level?: string }[];
}

export type SelfStatus = {
  state: 'ok' | 'degraded' | 'fail_closed';
  dependencies: {
    name: 'prometheus' | 'logs' | 'database' | 'actuator' | 'policy_layer2' | 'llm';
    state: 'up' | 'down' | 'disabled' | 'unknown';
    detail?: string;
  }[];
};

export type MetricName = 'error_ratio' | 'latency_p95_seconds' | 'throughput_rps' | 'queue_depth' | 'up';
export type AuditResponse = { chain_valid: boolean; events: AuditEvent[] };
