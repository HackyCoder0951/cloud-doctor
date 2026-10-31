"""Typed domain models mirroring contracts/schemas (frozen v1). ``to_contract`` yields the contract JSON."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, PlainSerializer, StringConstraints

from .clock import iso


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return dt.astimezone(UTC)


Ts = Annotated[datetime, AfterValidator(_utc), PlainSerializer(iso, return_type=str, when_used="always")]
IncidentId = Annotated[str, StringConstraints(pattern=r"^INC-[0-9]{4,}$")]
EvidenceId = Annotated[str, StringConstraints(pattern=r"^EV-[0-9]{3,}$")]
PlanId = Annotated[str, StringConstraints(pattern=r"^PL-[0-9]{4,}$")]
DecisionId = Annotated[str, StringConstraints(pattern=r"^DEC-[0-9]{4,}$")]
ExecutionId = Annotated[str, StringConstraints(pattern=r"^EX-[0-9]{4,}$")]
EventId = Annotated[str, StringConstraints(pattern=r"^TL-[0-9]{4,}$")]
ServiceName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{1,40}$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]

HealthState = Literal["HEALTHY", "DEGRADED", "UNHEALTHY", "UNKNOWN"]
MissingSignal = Literal["none", "no_data_expected", "no_data_unexpected", "collection_failed"]
RiskClass = Literal["low", "medium", "high"]
ActionId = Literal["restart_service", "rollback_service", "scale_service", "clear_cache", "isolate_dependency", "escalate"]
EvidenceStatus = Literal["ok", "empty", "error", "timeout"]
ClaimType = Literal["observation", "temporal_correlation", "inference", "hypothesis"]
Origin = Literal["rule", "llm"]
DecisionResult = Literal["allow", "allow_with_approval", "deny"]
IncidentState = Literal["detected", "investigating", "diagnosed", "remediating", "verifying", "recovered", "escalated", "closed"]
Verdict = Literal["recovered", "partial", "failed", "regression", "relapse", "unverifiable"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    def to_contract(self) -> dict:
        return self.model_dump(mode="json", exclude_none=True)


class Evidence(Model):
    evidence_id: EvidenceId
    incident_id: IncidentId
    source: Literal["prometheus", "loki", "container_event", "health_probe", "synthetic_probe", "deploy_event", "alert"]
    type: Literal["metric", "log", "event", "probe"]
    service: ServiceName
    observed_at: Ts
    collected_at: Ts
    query: Annotated[str, StringConstraints(max_length=2000)]
    status: EvidenceStatus
    missing_signal_state: MissingSignal = "none"
    summary: Annotated[str, StringConstraints(max_length=500)] | None = None
    payload: dict[str, Any]
    payload_hash: Sha256
    untrusted: bool


class Incident(Model):
    incident_id: IncidentId
    state: IncidentState
    opened_at: Ts
    closed_at: Ts | None = None
    severity: Literal["low", "medium", "high", "critical"]
    services: Annotated[list[ServiceName], Field(min_length=1)]
    symptoms: list[Annotated[str, StringConstraints(max_length=200)]] = Field(default_factory=list)
    outcome: Literal["mitigated", "escalated", "unresolved"] | None = None
    root_cause_confirmed: bool = False
    run_id: str | None = None


class TimelineEvent(Model):
    event_id: EventId
    incident_id: IncidentId
    event_time: Ts
    collected_at: Ts
    kind: Literal["alert", "metric_change", "log_burst", "container_event", "deploy_event", "diagnosis",
                  "policy_decision", "action", "verification", "note"]
    service: ServiceName | None = None
    summary: Annotated[str, StringConstraints(max_length=300)]
    evidence_refs: list[EvidenceId] = Field(default_factory=list)
    suppressed: bool = False


class Claim(Model):
    text: Annotated[str, StringConstraints(max_length=500)]
    type: ClaimType
    evidence: Annotated[list[EvidenceId], Field(min_length=1)]


class Hypothesis(Model):
    rank: Annotated[int, Field(ge=1)]
    cause_id: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{2,60}$")]
    service: ServiceName | None = None
    description: Annotated[str, StringConstraints(max_length=500)]
    confidence: Annotated[float, Field(ge=0, le=1)]
    confidence_basis: list[str] = Field(default_factory=list)
    status: Literal["candidate", "supported", "refuted", "confirmed"]
    claims: Annotated[list[Claim], Field(min_length=1)]
    contradicting: list[Claim] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)


class RecommendedAction(Model):
    action_id: ActionId
    params: dict[str, Any]


class Diagnosis(Model):
    incident_id: IncidentId
    generated_at: Ts
    origin: Origin
    engine_version: str | None = None
    hypotheses: Annotated[list[Hypothesis], Field(min_length=1)]
    recommended_action: RecommendedAction | None = None


class PlanParams(Model):
    service: ServiceName | None = None
    version: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._-]{1,64}$")] | None = None
    replicas: Annotated[int, Field(ge=1, le=5)] | None = None
    dependency: ServiceName | None = None
    reason: Annotated[str, StringConstraints(max_length=300)] | None = None


class Plan(Model):
    plan_id: PlanId
    incident_id: IncidentId
    action_id: ActionId
    params: PlanParams
    risk_class: RiskClass
    origin: Origin
    evidence_refs: Annotated[list[EvidenceId], Field(min_length=1)]
    rationale: Annotated[str, StringConstraints(max_length=500)]
    created_at: Ts
    plan_hash: Sha256


class L1(Model):
    result: Literal["pass", "deny"]
    rule_ids: list[Annotated[str, StringConstraints(pattern=r"^I-[0-9]{2}$")]]


class L2(Model):
    result: DecisionResult
    rule_ids: list[str]
    bundle_revision: str | None = None
    bundle_signed: bool | None = None


class Decision(Model):
    decision_id: DecisionId
    plan_id: PlanId
    plan_hash: Sha256
    l1: L1
    l2: L2 | None = None
    final: DecisionResult
    reasons: list[Annotated[str, StringConstraints(max_length=300)]] = Field(default_factory=list)
    invariants_version: str
    decided_at: Ts


class Execution(Model):
    execution_id: ExecutionId
    plan_id: PlanId
    idempotency_key: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{8,64}$")]
    started_at: Ts
    ended_at: Ts | None = None
    result: Literal["success", "failed", "refused"]
    refusal_rule_ids: list[str] | None = None
    executed_argv: list[str] | None = None
    detail: Annotated[str, StringConstraints(max_length=500)] | None = None


class Check(Model):
    name: Literal["readiness", "dependencies", "error_sli", "latency_sli", "synthetic_transaction", "no_regression", "telemetry_fresh"]
    passed: bool | None
    baseline: float | None = None
    pre_action: float | None = None
    post_action: float | None = None
    detail: Annotated[str, StringConstraints(max_length=300)] | None = None
    evidence: list[EvidenceId] | None = None

    def to_contract(self) -> dict:  # `passed` must be kept when null (fail-closed marker)
        d = self.model_dump(mode="json", exclude_none=True)
        d["passed"] = self.passed
        return d


class Verification(Model):
    incident_id: IncidentId
    execution_id: ExecutionId
    verdict: Verdict
    window_start: Ts
    window_end: Ts
    checks: Annotated[list[Check], Field(min_length=1)]

    def to_contract(self) -> dict:
        d = self.model_dump(mode="json", exclude_none=True, exclude={"checks"})
        d["checks"] = [c.to_contract() for c in self.checks]
        return d


class AuditEvent(Model):
    seq: Annotated[int, Field(ge=1)]
    incident_id: IncidentId | None = None
    actor: Annotated[str, StringConstraints(pattern=r"^(detector|rca|planner|policy|actuator|verifier|api|harness|operator:[A-Za-z0-9._-]{1,40})$")]
    event: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.]{2,60}$")]
    detail: dict[str, Any]
    prev_hash: Sha256
    hash: Sha256
    created_at: Ts


class Alert(Model):
    """Detector alert (table `alerts`; not a contract schema). ``observed_at`` is event time."""

    fingerprint: str
    service: ServiceName
    rule: str
    state: Literal["pending", "firing", "resolved"]
    layer: Literal["symptom", "dependency_state", "resource_saturation", "telemetry"]
    severity: Literal["warning", "critical"]
    observed_at: Ts  # when the condition began (event_time)
    fired_at: Ts  # when hysteresis entered firing (collected time)
    resolved_at: Ts | None = None
    summary: str
    value: float | None = None
    incident_id: IncidentId | None = None
    suppressed: bool = False
    suppress_reason: str | None = None
