-- Cloud Doctor database schema — frozen contract v1 (PostgreSQL 18).
-- The backend converts this to Alembic migration 0001 UNCHANGED in meaning.
-- Design rules (docs/10-architecture/data-architecture.md, tech-stack.md):
--  * evidence payloads are JSONB; NUL characters must be stripped before insert (JSONB rejects \u0000);
--  * payload_hash is computed over the canonical JSON BEFORE insert (JSONB does not preserve key order/whitespace);
--  * the audit log is append-only and hash-chained; UPDATE/DELETE/TRUNCATE are rejected by triggers and the
--    application role only receives INSERT and SELECT on it.

CREATE TABLE services (
    name         text PRIMARY KEY CHECK (name ~ '^[a-z][a-z0-9-]{1,40}$'),
    kind         text NOT NULL,
    container    text NOT NULL UNIQUE,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE service_dependencies (
    service      text NOT NULL REFERENCES services(name),
    depends_on   text NOT NULL REFERENCES services(name),
    kind         text NOT NULL CHECK (kind IN ('hard', 'soft')),
    PRIMARY KEY (service, depends_on),
    CHECK (service <> depends_on)
);

CREATE SEQUENCE incident_seq;
CREATE TABLE incidents (
    incident_id          text PRIMARY KEY CHECK (incident_id ~ '^INC-[0-9]{4,}$'),
    state                text NOT NULL CHECK (state IN ('detected','investigating','diagnosed','remediating','verifying','recovered','escalated','closed')),
    severity             text NOT NULL CHECK (severity IN ('low','medium','high','critical')),
    opened_at            timestamptz NOT NULL,
    closed_at            timestamptz,
    services             text[] NOT NULL,
    symptoms             text[] NOT NULL DEFAULT '{}',
    outcome              text CHECK (outcome IN ('mitigated','escalated','unresolved')),
    root_cause_confirmed boolean NOT NULL DEFAULT false,
    run_id               text
);
CREATE INDEX incidents_state_opened_idx ON incidents (state, opened_at DESC);

CREATE TABLE alerts (
    alert_id     bigserial PRIMARY KEY,
    incident_id  text REFERENCES incidents(incident_id),
    service      text NOT NULL REFERENCES services(name),
    rule         text NOT NULL,
    state        text NOT NULL CHECK (state IN ('pending','firing','resolved')),
    fired_at     timestamptz NOT NULL,
    resolved_at  timestamptz,
    fingerprint  text NOT NULL,
    UNIQUE (fingerprint, fired_at)
);
CREATE INDEX alerts_service_fired_idx ON alerts (service, fired_at DESC);

CREATE TABLE evidence (
    incident_id          text NOT NULL REFERENCES incidents(incident_id),
    evidence_id          text NOT NULL CHECK (evidence_id ~ '^EV-[0-9]{3,}$'),
    source               text NOT NULL,
    type                 text NOT NULL CHECK (type IN ('metric','log','event','probe')),
    service              text NOT NULL REFERENCES services(name),
    observed_at          timestamptz NOT NULL,
    collected_at         timestamptz NOT NULL,
    query                text NOT NULL,
    status               text NOT NULL CHECK (status IN ('ok','empty','error','timeout')),
    missing_signal_state text NOT NULL DEFAULT 'none' CHECK (missing_signal_state IN ('none','no_data_expected','no_data_unexpected','collection_failed')),
    summary              text,
    payload              jsonb NOT NULL,
    payload_hash         text NOT NULL CHECK (payload_hash ~ '^sha256:[0-9a-f]{64}$'),
    untrusted            boolean NOT NULL,
    PRIMARY KEY (incident_id, evidence_id)
);
CREATE INDEX evidence_service_time_idx ON evidence (incident_id, service, observed_at);
CREATE INDEX evidence_payload_gin_idx ON evidence USING GIN (payload jsonb_path_ops);

CREATE TABLE timeline_events (
    event_id      text NOT NULL CHECK (event_id ~ '^TL-[0-9]{4,}$'),
    incident_id   text NOT NULL REFERENCES incidents(incident_id),
    event_time    timestamptz NOT NULL,
    collected_at  timestamptz NOT NULL,
    kind          text NOT NULL,
    service       text REFERENCES services(name),
    summary       text NOT NULL,
    evidence_refs text[] NOT NULL DEFAULT '{}',
    suppressed    boolean NOT NULL DEFAULT false,
    PRIMARY KEY (incident_id, event_id)
);
CREATE INDEX timeline_incident_time_idx ON timeline_events (incident_id, event_time);

CREATE TABLE hypotheses (
    incident_id  text NOT NULL REFERENCES incidents(incident_id),
    rank         integer NOT NULL CHECK (rank >= 1),
    cause_id     text NOT NULL,
    service      text REFERENCES services(name),
    description  text NOT NULL,
    confidence   double precision NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    status       text NOT NULL CHECK (status IN ('candidate','supported','refuted','confirmed')),
    origin       text NOT NULL CHECK (origin IN ('rule','llm')),
    body         jsonb NOT NULL,           -- full hypothesis object as in contracts/schemas/diagnosis.json
    generated_at timestamptz NOT NULL,
    PRIMARY KEY (incident_id, generated_at, rank)
);

CREATE TABLE plans (
    plan_id       text PRIMARY KEY CHECK (plan_id ~ '^PL-[0-9]{4,}$'),
    incident_id   text NOT NULL REFERENCES incidents(incident_id),
    action_id     text NOT NULL CHECK (action_id IN ('restart_service','rollback_service','scale_service','clear_cache','isolate_dependency','escalate')),
    params        jsonb NOT NULL,
    risk_class    text NOT NULL CHECK (risk_class IN ('low','medium','high')),
    origin        text NOT NULL CHECK (origin IN ('rule','llm')),
    evidence_refs text[] NOT NULL,
    rationale     text NOT NULL,
    plan_hash     text NOT NULL CHECK (plan_hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at    timestamptz NOT NULL
);
CREATE INDEX plans_incident_idx ON plans (incident_id, created_at);

CREATE TABLE policy_decisions (
    decision_id        text PRIMARY KEY CHECK (decision_id ~ '^DEC-[0-9]{4,}$'),
    plan_id            text NOT NULL REFERENCES plans(plan_id),
    plan_hash          text NOT NULL,
    l1                 jsonb NOT NULL,
    l2                 jsonb,
    final              text NOT NULL CHECK (final IN ('allow','allow_with_approval','deny')),
    reasons            text[] NOT NULL DEFAULT '{}',
    invariants_version text NOT NULL,
    decided_at         timestamptz NOT NULL
);

CREATE TABLE approvals (
    plan_id     text NOT NULL REFERENCES plans(plan_id),
    plan_hash   text NOT NULL,
    approver    text NOT NULL,
    decision    text NOT NULL CHECK (decision IN ('approved','rejected')),
    reason      text NOT NULL,
    decided_at  timestamptz NOT NULL,
    PRIMARY KEY (plan_id, decided_at)
);

CREATE TABLE executions (
    execution_id     text PRIMARY KEY CHECK (execution_id ~ '^EX-[0-9]{4,}$'),
    plan_id          text NOT NULL REFERENCES plans(plan_id),
    idempotency_key  text NOT NULL UNIQUE,
    started_at       timestamptz NOT NULL,
    ended_at         timestamptz,
    result           text NOT NULL CHECK (result IN ('success','failed','refused')),
    refusal_rule_ids text[] NOT NULL DEFAULT '{}',
    executed_argv    text[] NOT NULL DEFAULT '{}',
    detail           text
);

CREATE TABLE verifications (
    verification_id bigserial PRIMARY KEY,
    incident_id     text NOT NULL REFERENCES incidents(incident_id),
    execution_id    text NOT NULL REFERENCES executions(execution_id),
    verdict         text NOT NULL CHECK (verdict IN ('recovered','partial','failed','regression','relapse','unverifiable')),
    window_start    timestamptz NOT NULL,
    window_end      timestamptz NOT NULL,
    checks          jsonb NOT NULL
);

CREATE TABLE experiment_runs (
    run_id       text PRIMARY KEY,
    scenario_id  text NOT NULL,
    metadata     jsonb NOT NULL,
    injected_at  timestamptz,
    ground_truth jsonb            -- written by the harness only; never read by detector or RCA
);

-- Audit log: append-only, hash-chained. -------------------------------------------------
CREATE TABLE audit_log (
    seq          bigint PRIMARY KEY,
    incident_id  text,
    actor        text NOT NULL CHECK (actor ~ '^(detector|rca|planner|policy|actuator|verifier|api|harness|operator:[A-Za-z0-9._-]{1,40})$'),
    event        text NOT NULL CHECK (event ~ '^[a-z][a-z0-9_.]{2,60}$'),
    detail       jsonb NOT NULL,
    prev_hash    text NOT NULL CHECK (prev_hash ~ '^sha256:[0-9a-f]{64}$'),
    hash         text NOT NULL UNIQUE CHECK (hash ~ '^sha256:[0-9a-f]{64}$'),
    created_at   timestamptz NOT NULL
);
CREATE INDEX audit_incident_seq_idx ON audit_log (incident_id, seq);

CREATE FUNCTION audit_log_guard_insert() RETURNS trigger AS $$
DECLARE
    last_seq  bigint;
    last_hash text;
BEGIN
    PERFORM pg_advisory_xact_lock(727001);                      -- serialise chain writers
    SELECT seq, hash INTO last_seq, last_hash FROM audit_log ORDER BY seq DESC LIMIT 1;
    IF last_seq IS NULL THEN
        IF NEW.seq <> 1 OR NEW.prev_hash <> 'sha256:' || repeat('0', 64) THEN
            RAISE EXCEPTION 'audit chain must start at seq 1 with a zero prev_hash';
        END IF;
    ELSE
        IF NEW.seq <> last_seq + 1 OR NEW.prev_hash <> last_hash THEN
            RAISE EXCEPTION 'audit chain broken: expected seq % and prev_hash %', last_seq + 1, last_hash;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER audit_log_insert_guard BEFORE INSERT ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_guard_insert();

CREATE FUNCTION audit_log_reject_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only (% rejected)', TG_OP;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER audit_log_no_update_delete BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_reject_change();
CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION audit_log_reject_change();

-- Roles: the application role may only INSERT/SELECT on the audit log (the owner role runs migrations).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cloud_doctor_app') THEN
        CREATE ROLE cloud_doctor_app NOLOGIN;
    END IF;
END $$;
GRANT SELECT, INSERT, UPDATE ON incidents, alerts, timeline_events, hypotheses, plans, policy_decisions, approvals, executions, verifications, experiment_runs TO cloud_doctor_app;
GRANT SELECT, INSERT ON evidence, services, service_dependencies TO cloud_doctor_app;
REVOKE ALL ON audit_log FROM cloud_doctor_app;
GRANT SELECT, INSERT ON audit_log TO cloud_doctor_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cloud_doctor_app;
