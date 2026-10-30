// Pure request router for the mock API (contracts/openapi.yaml, base path /api/v1 already stripped).
// Used by mock/server.mjs (real HTTP) and by the tests (stubbed fetch), so both see the same data.
import { buildAudit, buildIncidents, metricSeries, serviceLogs, SERVICES, sha, tamper, topology, ts } from './data.mjs';

const RE = {
  incident: /^INC-[0-9]{4,}$/, plan: /^PL-[0-9]{4,}$/, service: /^[a-z][a-z0-9-]{1,40}$/,
  idem: /^[A-Za-z0-9_-]{8,64}$/, sha: /^sha256:[0-9a-f]{64}$/,
};
const STATES = ['detected', 'investigating', 'diagnosed', 'remediating', 'verifying', 'recovered', 'escalated', 'closed'];
const METRICS = ['error_ratio', 'latency_p95_seconds', 'throughput_rps', 'queue_depth', 'up'];

const json = (status, body) => ({ status, body });
const err = (status, code, message, rule_ids) => json(status, { code, message, ...(rule_ids ? { rule_ids } : {}) });
const intParam = (q, name, def, min, max) => {
  const raw = q.get(name);
  if (raw === null) return def;
  const n = Number(raw);
  return Number.isInteger(n) && n >= min && n <= max ? n : null;
};

export function createMock({ now = () => Date.now() } = {}) {
  const incidents = buildIncidents();
  const audit = buildAudit();
  const status = { state: 'degraded', dependencies: [
    { name: 'prometheus', state: 'up' }, { name: 'logs', state: 'down', detail: 'Loki query timeouts; log evidence is unavailable' },
    { name: 'database', state: 'up' }, { name: 'actuator', state: 'up' }, { name: 'policy_layer2', state: 'up' }, { name: 'llm', state: 'disabled', detail: 'C0: deterministic mode' } ] };
  const idem = new Map();
  const listeners = new Set();
  let eventId = 0;
  const buffer = [];

  function emit(type, fields = {}) {
    const ev = { id: ++eventId, payload: { type, at: new Date(now()).toISOString(), ...fields } };
    buffer.push(ev);
    if (buffer.length > 200) buffer.shift();
    listeners.forEach((l) => l(ev));
    return ev;
  }
  const subscribe = (fn) => { listeners.add(fn); return () => listeners.delete(fn); };
  const eventsAfter = (id) => buffer.filter((e) => e.id > id);

  function setStatus(state) {
    status.state = state;
    if (state === 'fail_closed') status.dependencies = status.dependencies.map((d) => (d.name === 'actuator' || d.name === 'database' ? { ...d, state: 'down', detail: 'unreachable: all actions denied' } : d));
    if (state === 'ok') status.dependencies = status.dependencies.map((d) => (d.state === 'down' ? { name: d.name, state: 'up' } : d));
    emit('status.changed', { data: { state } });
  }

  function approve(inc, planId, key, body) {
    const b = incidents[inc];
    const plan = b?.remediation.plans.find((p) => p.plan_id === planId);
    if (!plan) return err(404, 'not_found', 'plan not found');
    if (!body || typeof body.plan_hash !== 'string' || !RE.sha.test(body.plan_hash) || typeof body.reason !== 'string' || body.reason.length < 3 || body.reason.length > 300) return err(422, 'invalid_body', 'plan_hash and reason (3-300 chars) are required');
    const dec = b.remediation.decisions.find((d) => d.plan_id === planId);
    const executed = b.remediation.executions.some((e) => e.plan_id === planId);
    if (plan.risk_class !== 'medium' || dec?.final !== 'allow_with_approval' || executed) return err(409, 'plan_not_pending', 'plan is not awaiting approval');
    if (body.plan_hash !== plan.plan_hash) return err(409, 'plan_hash_mismatch', 'plan_hash does not match the stored plan');
    const n = b.remediation.decisions.length + 1;
    const decision = { decision_id: `DEC-${String(900 + n).padStart(4, '0')}`, plan_id: planId, plan_hash: plan.plan_hash, l1: dec.l1, ...(dec.l2 ? { l2: { ...dec.l2, result: 'allow' } } : {}), final: 'allow', reasons: [...dec.reasons, 'operator approval bound to plan_hash'], invariants_version: dec.invariants_version, decided_at: new Date(now()).toISOString() };
    b.remediation.decisions.push(decision);
    b.incident.state = 'remediating';
    emit('decision.recorded', { incident_id: inc, data: { plan_id: planId, final: 'allow' } });
    emit('incident.updated', { incident_id: inc, data: { state: 'remediating' } });
    return json(200, decision);
  }

  /** Simulates the (system-initiated) execution + verification that follows an approval. */
  function completeApproved(inc, planId) {
    const b = incidents[inc];
    const plan = b.remediation.plans.find((p) => p.plan_id === planId);
    if (!plan || b.remediation.executions.some((e) => e.plan_id === planId)) return;
    const n = b.remediation.executions.length + 1;
    const exec = { execution_id: `EX-${String(900 + n).padStart(4, '0')}`, plan_id: planId, idempotency_key: `mock-${planId.toLowerCase()}`, started_at: new Date(now()).toISOString(), ended_at: new Date(now()).toISOString(), result: 'success', executed_argv: ['docker', 'restart', `cd-${plan.params.service}`], detail: 'container restarted' };
    b.remediation.executions.push(exec);
    b.incident.state = 'verifying';
    emit('execution.finished', { incident_id: inc, data: { execution_id: exec.execution_id, result: 'success' } });
    emit('incident.updated', { incident_id: inc, data: { state: 'verifying' } });
  }

  function handle({ method, path, query = new URLSearchParams(), headers = {}, body }) {
    const seg = path.replace(/\/+$/, '').split('/').filter(Boolean).map(decodeURIComponent);
    const key = headers['idempotency-key'];
    const accept = headers.accept ?? '';
    const [a, b, c, d, e, f] = seg;

    if (method === 'GET' && a === 'status' && seg.length === 1) return json(200, status);

    if (method === 'GET' && a === 'services' && seg.length === 1) return json(200, SERVICES);
    if (method === 'GET' && a === 'services' && RE.service.test(b ?? '') && seg.length === 3) {
      const svc = SERVICES.find((s) => s.name === b);
      if (!svc) return err(404, 'not_found', 'service not found');
      if (c === 'health') return json(200, svc);
      if (c === 'metrics') {
        const name = query.get('name');
        const since = intParam(query, 'since_seconds', 600, 30, 3600);
        if (!METRICS.includes(name) || since === null) return err(422, 'invalid_query', 'bad metric query');
        return json(200, metricSeries(b, name, since, now()));
      }
      if (c === 'logs') {
        const since = intParam(query, 'since_seconds', 300, 30, 3600);
        const limit = intParam(query, 'limit', 100, 1, 500);
        if (since === null || limit === null) return err(422, 'invalid_query', 'bad log query');
        return json(200, serviceLogs(b, since, limit, now()));
      }
    }
    if (method === 'GET' && a === 'topology') return json(200, topology());

    if (a === 'incidents' && seg.length === 1 && method === 'GET') {
      const st = query.get('state');
      if (st !== null && !STATES.includes(st)) return err(422, 'invalid_query', 'bad state');
      const limit = intParam(query, 'limit', 50, 1, 200);
      if (limit === null) return err(422, 'invalid_query', 'bad limit');
      const list = Object.values(incidents).map((x) => x.incident).filter((i) => !st || i.state === st).sort((x, y) => (x.opened_at < y.opened_at ? 1 : -1));
      return json(200, list.slice(0, limit));
    }

    if (a === 'incidents' && RE.incident.test(b ?? '')) {
      const inc = incidents[b];
      if (!inc) return err(404, 'not_found', 'incident not found');
      if (seg.length === 2 && method === 'GET') return json(200, inc.incident);
      if (c === 'timeline' && method === 'GET' && seg.length === 3) return json(200, [...inc.timeline].sort((x, y) => (x.event_time < y.event_time ? -1 : 1)));
      if (c === 'evidence' && method === 'GET' && seg.length === 3) return json(200, inc.evidence);
      if (c === 'diagnosis' && method === 'GET' && seg.length === 3) return inc.diagnosis ? json(200, inc.diagnosis) : err(404, 'not_found', 'no diagnosis yet');
      if (c === 'diagnose' && method === 'POST' && seg.length === 3) {
        if (!key || !RE.idem.test(key)) return err(422, 'invalid_idempotency_key', 'Idempotency-Key required');
        emit('incident.updated', { incident_id: b, data: { rediagnose: true } });
        return json(202, null);
      }
      if (c === 'remediation' && method === 'GET' && seg.length === 3) return json(200, inc.remediation);
      if (c === 'remediation' && d === 'plans' && RE.plan.test(e ?? '') && method === 'POST' && seg.length === 6) {
        if (!key || !RE.idem.test(key)) return err(422, 'invalid_idempotency_key', 'Idempotency-Key required');
        const cacheKey = `${path}|${key}`;
        if (idem.has(cacheKey)) return idem.get(cacheKey);
        let res;
        if (f === 'approve') res = approve(b, e, key, body);
        else if (f === 'reject') {
          const plan = inc.remediation.plans.find((p) => p.plan_id === e);
          if (!plan) res = err(404, 'not_found', 'plan not found');
          else if (!body || typeof body.reason !== 'string' || body.reason.length < 3 || body.reason.length > 300) res = err(422, 'invalid_body', 'reason (3-300 chars) required');
          else {
            const dec = inc.remediation.decisions.find((x) => x.plan_id === e);
            if (dec?.final !== 'allow_with_approval') res = err(409, 'plan_not_pending', 'plan is not awaiting approval');
            else {
              dec.final = 'deny';
              dec.reasons = [...dec.reasons, 'rejected by operator'];
              inc.incident.state = 'escalated';
              emit('decision.recorded', { incident_id: b, data: { plan_id: e, final: 'deny' } });
              res = json(200, null);
            }
          }
        }
        if (res) { if (res.status < 500) idem.set(cacheKey, res); return res; }
      }
      if (c === 'verification' && method === 'GET' && seg.length === 3) return json(200, inc.verification);
      if (c === 'report' && method === 'GET' && seg.length === 3) {
        if (!inc.report) return err(404, 'not_found', 'report not available yet');
        return accept.includes('text/markdown') ? { status: 200, text: renderMarkdown(inc.report), contentType: 'text/markdown; charset=utf-8' } : json(200, inc.report);
      }
    }

    if (a === 'audit' && seg.length === 1 && method === 'GET') {
      const incident = query.get('incident');
      const after = intParam(query, 'after_seq', 0, 0, Number.MAX_SAFE_INTEGER);
      const limit = intParam(query, 'limit', 100, 1, 500);
      if ((incident !== null && !RE.incident.test(incident)) || after === null || limit === null) return err(422, 'invalid_query', 'bad audit query');
      // Mock behaviour: the INC-0003 view returns a broken chain so the UI shows the invalid badge.
      const broken = incident === 'INC-0003';
      let events = broken ? tamper(audit) : audit;
      events = events.filter((x) => (!incident || x.incident_id === incident) && x.seq > after).slice(0, limit);
      return json(200, { chain_valid: !broken, events });
    }

    return err(404, 'not_found', 'no such endpoint');
  }

  return { handle, emit, subscribe, eventsAfter, setStatus, completeApproved, incidents, status, get lastEventId() { return eventId; } };
}

export function renderMarkdown(r) {
  const L = [];
  L.push(`# Incident report ${r.incident.incident_id}`, '', `Generated: ${r.generated_at} (${r.generator.mode}, ${r.generator.version})`, '');
  L.push(`State: ${r.incident.state}; severity: ${r.incident.severity}; services: ${r.incident.services.join(', ')}`, '');
  L.push('## Outcome', '', `- mitigated: ${r.outcome.mitigated}`, `- root_cause_confirmed: ${r.outcome.root_cause_confirmed}`, `- escalated: ${r.outcome.escalated}`, '');
  L.push('## Diagnosis (confidence is a ranking aid, not a probability)', '');
  for (const h of r.diagnosis.hypotheses) L.push(`${h.rank}. ${h.cause_id} (${h.status}, score ${h.confidence}) - ${h.description}`);
  L.push('', '## Timeline', '');
  for (const t of r.timeline) L.push(`- ${t.event_time} [${t.kind}] ${t.summary}${t.suppressed ? ' (suppressed)' : ''}`);
  L.push('', '## Executions', '');
  for (const x of r.executions) L.push(`- ${x.execution_id} ${x.result}: ${x.executed_argv?.length ? x.executed_argv.join(' ') : '(no command)'}`);
  L.push('', '## Verification', '');
  for (const v of r.verifications) L.push(`- ${v.execution_id}: ${v.verdict}`);
  L.push('', '## Limitations', '');
  for (const l of r.limitations) L.push(`- ${l}`);
  return `${L.join('\n')}\n`;
}

export { sha, ts };
