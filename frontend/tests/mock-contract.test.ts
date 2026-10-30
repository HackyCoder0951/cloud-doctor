// The mock must honour contracts/openapi.yaml: every path is routed and every response body
// validates against the contract JSON Schemas (so the UI is built against contract-shaped data).
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import Ajv2020 from 'ajv/dist/2020.js';
import addFormats from 'ajv-formats';
import { parse } from 'yaml';
import { describe, expect, it } from 'vitest';
import { createMock } from '../mock/router.mjs';

const contracts = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'contracts');
const openapi = parse(readFileSync(join(contracts, 'openapi.yaml'), 'utf8')) as { paths: Record<string, Record<string, { operationId: string }>> };

const rawOpenapi = readFileSync(join(contracts, 'openapi.yaml'), 'utf8');
const A = new Ajv2020({ strict: false, allErrors: true });
addFormats(A);
for (const f of readdirSync(join(contracts, 'schemas'))) A.addSchema(JSON.parse(readFileSync(join(contracts, 'schemas', f), 'utf8')));
// Make the OpenAPI document addressable: relative ./schemas refs become absolute schema ids.
const OPENAPI_ID = 'https://cloud-doctor.local/openapi';
A.addSchema({ ...JSON.parse(JSON.stringify(parse(rawOpenapi)).replaceAll('"./schemas/', '"https://cloud-doctor.local/schemas/')), $id: OPENAPI_ID });
const esc = (p: string) => p.replaceAll('~', '~0').replaceAll('/', '~1');
/** Validator for the 200 JSON response of an operation, taken straight from openapi.yaml. */
const responseSchema = (path: string, mediaType = 'application/json') =>
  A.compile({ $ref: `${OPENAPI_ID}#/paths/${esc(path)}/get/responses/200/content/${esc(mediaType)}/schema` });
const S = (name: string) => A.compile({ $ref: `https://cloud-doctor.local/schemas/${name}.json` });
const component = (name: string) => A.compile({ $ref: `${OPENAPI_ID}#/components/schemas/${name}` });
const valid = (v: ReturnType<typeof A.compile>, body: unknown) => (v(body) ? [] : v.errors);

const mock = createMock();
const get = (path: string, query = '', accept = 'application/json') => mock.handle({ method: 'GET', path, query: new URLSearchParams(query), headers: { accept } });
const INCIDENTS = Object.keys(mock.incidents);

describe('mock covers every operation in contracts/openapi.yaml', () => {
  const samples: Record<string, [string, string]> = {
    '/services': ['GET', '/services'],
    '/services/{service}/health': ['GET', '/services/api/health'],
    '/services/{service}/metrics': ['GET', '/services/api/metrics?name=up'],
    '/services/{service}/logs': ['GET', '/services/api/logs'],
    '/topology': ['GET', '/topology'],
    '/incidents': ['GET', '/incidents'],
    '/incidents/{incident}': ['GET', '/incidents/INC-0001'],
    '/incidents/{incident}/timeline': ['GET', '/incidents/INC-0001/timeline'],
    '/incidents/{incident}/evidence': ['GET', '/incidents/INC-0001/evidence'],
    '/incidents/{incident}/diagnosis': ['GET', '/incidents/INC-0001/diagnosis'],
    '/incidents/{incident}/remediation': ['GET', '/incidents/INC-0001/remediation'],
    '/incidents/{incident}/verification': ['GET', '/incidents/INC-0001/verification'],
    '/incidents/{incident}/report': ['GET', '/incidents/INC-0001/report'],
    '/audit': ['GET', '/audit'],
    '/status': ['GET', '/status'],
  };
  it('lists the same GET paths as the contract (plus POST paths handled below)', () => {
    const contractGets = Object.entries(openapi.paths).filter(([, v]) => v.get).map(([p]) => p).filter((p) => p !== '/stream');
    expect(Object.keys(samples).sort()).toEqual(contractGets.sort());
  });
  it.each(Object.entries(samples))('routes %s', (_p, [method, url]) => {
    const [path, qs = ''] = url.split('?');
    const r = mock.handle({ method, path: path!, query: new URLSearchParams(qs), headers: {} });
    expect(r.status).toBe(200);
  });
  it('routes the POST operations (login, logout, diagnose, approve, reject)', () => {
    const idem = { 'idempotency-key': 'abcdefgh1234' };
    expect(mock.handle({ method: 'POST', path: '/auth/login', body: { token: 'longenough' } }).status).toBe(204);
    expect(mock.handle({ method: 'POST', path: '/auth/login', body: { token: 'short' } }).status).toBe(401);
    expect(mock.handle({ method: 'POST', path: '/auth/logout' }).status).toBe(204);
    expect(mock.handle({ method: 'POST', path: '/incidents/INC-0001/diagnose', headers: idem }).status).toBe(202);
    expect(mock.handle({ method: 'POST', path: '/incidents/INC-0001/diagnose', headers: {} }).status).toBe(422);
    const fresh = createMock();
    expect(fresh.handle({ method: 'POST', path: '/incidents/INC-0002/remediation/plans/PL-0101/reject', headers: idem, body: { reason: 'no thanks' } }).status).toBe(200);
  });
});

describe('mock responses validate against the contract schemas', () => {
  it('the validators are not vacuous: they reject invalid bodies', () => {
    expect(valid(responseSchema('/services'), [{ name: 'api' }])).not.toEqual([]);
    expect(valid(responseSchema('/audit'), { chain_valid: 'yes', events: [] })).not.toEqual([]);
    expect(valid(responseSchema('/incidents/{incident}/diagnosis'), { incident_id: 'INC-0001' })).not.toEqual([]);
    expect(valid(responseSchema('/services/{service}/metrics'), { service: 'api', name: 'up', status: 'bogus', points: [] })).not.toEqual([]);
    expect(valid(S('plan'), { plan_id: 'PL-0001' })).not.toEqual([]);
  });

  it('every GET response of every incident and service', () => {
    const checks: Array<[string, string, string]> = [];
    const v = {
      services: responseSchema('/services'), health: responseSchema('/services/{service}/health'), metrics: responseSchema('/services/{service}/metrics'),
      logs: responseSchema('/services/{service}/logs'), topology: responseSchema('/topology'), incidents: responseSchema('/incidents'),
      incident: responseSchema('/incidents/{incident}'), timeline: responseSchema('/incidents/{incident}/timeline'), evidence: responseSchema('/incidents/{incident}/evidence'),
      diagnosis: responseSchema('/incidents/{incident}/diagnosis'), remediation: responseSchema('/incidents/{incident}/remediation'),
      verification: responseSchema('/incidents/{incident}/verification'), report: responseSchema('/incidents/{incident}/report'), audit: responseSchema('/audit'), status: responseSchema('/status'),
    };
    const run = (name: keyof typeof v, path: string, query = '') => {
      const r = get(path, query);
      if (r.status === 404) return; // documented 404 (e.g. no diagnosis yet)
      expect(r.status, path).toBe(200);
      const errs = valid(v[name], r.body);
      if (errs && errs.length) checks.push([name, path, JSON.stringify(errs.slice(0, 3))]);
    };
    run('services', '/services'); run('topology', '/topology'); run('incidents', '/incidents'); run('status', '/status');
    run('audit', '/audit'); run('audit', '/audit', 'incident=INC-0003'); run('audit', '/audit', 'incident=INC-0001&after_seq=2&limit=2');
    for (const s of mock.handle({ method: 'GET', path: '/services' }).body as Array<{ name: string }>) {
      run('health', `/services/${s.name}/health`);
      for (const n of ['error_ratio', 'latency_p95_seconds', 'throughput_rps', 'queue_depth', 'up']) run('metrics', `/services/${s.name}/metrics`, `name=${n}&since_seconds=300`);
      run('logs', `/services/${s.name}/logs`, 'limit=20');
    }
    for (const id of INCIDENTS) {
      run('incident', `/incidents/${id}`); run('timeline', `/incidents/${id}/timeline`); run('evidence', `/incidents/${id}/evidence`); run('diagnosis', `/incidents/${id}/diagnosis`);
      run('remediation', `/incidents/${id}/remediation`); run('verification', `/incidents/${id}/verification`); run('report', `/incidents/${id}/report`);
    }
    expect(checks).toEqual([]);
  });

  it('covers the required scenario variety', () => {
    const services = get('/services').body as Array<{ state: string; missing_signal_state: string }>;
    expect(new Set(services.filter((s) => s.state === 'UNKNOWN').map((s) => s.missing_signal_state))).toEqual(new Set(['no_data_expected', 'no_data_unexpected', 'collection_failed']));
    const states = new Set(Object.values(mock.incidents).map((i: { incident: { state: string } }) => i.incident.state));
    for (const st of ['detected', 'diagnosed', 'remediating', 'verifying', 'recovered', 'escalated', 'closed']) expect(states.has(st), st).toBe(true);
    const r03 = mock.incidents['INC-0003'].remediation;
    expect(r03.circuit_breaker).toBe('open');
    expect(r03.attempts_remaining).toBe(0);
    expect(r03.executions.some((e: { result: string }) => e.result === 'refused')).toBe(true);
    const p = mock.incidents['INC-0002'].remediation;
    expect(p.plans[0].risk_class).toBe('medium');
    expect(p.decisions[0].final).toBe('allow_with_approval');
    expect((get('/audit').body as { chain_valid: boolean }).chain_valid).toBe(true);
    expect((get('/audit', 'incident=INC-0003').body as { chain_valid: boolean }).chain_valid).toBe(false);
    expect(Object.values(mock.incidents).some((i: { verification: Array<{ verdict: string }> }) => i.verification.some((v) => v.verdict === 'unverifiable'))).toBe(true);
  });

  it('markdown report and error bodies', () => {
    const md = get('/incidents/INC-0001/report', '', 'text/markdown');
    expect(md.contentType).toContain('text/markdown');
    expect(md.text).toContain('# Incident report INC-0001');
    const e = component('Error');
    expect(valid(e, get('/incidents/INC-9999').body)).toEqual([]);
    expect(valid(e, mock.handle({ method: 'POST', path: '/incidents/INC-0002/remediation/plans/PL-0101/approve', headers: { 'idempotency-key': 'abcdefgh1234' }, body: { plan_hash: `sha256:${'1'.repeat(64)}`, reason: 'abc' } }).body)).toEqual([]);
  });

  it('approve returns a contract decision and SSE events match StreamEvent', () => {
    const m = createMock();
    const events: Array<{ payload: unknown }> = [];
    m.subscribe((e) => events.push(e));
    const plan = m.incidents['INC-0002'].remediation.plans[0];
    const r = m.handle({ method: 'POST', path: '/incidents/INC-0002/remediation/plans/PL-0101/approve', headers: { 'idempotency-key': 'abcdefgh1234' }, body: { plan_hash: plan.plan_hash, reason: 'verified' } });
    expect(r.status).toBe(200);
    expect(valid(S('decision'), r.body)).toEqual([]);
    // replay with the same key returns the identical stored response and does not re-execute
    const again = m.handle({ method: 'POST', path: '/incidents/INC-0002/remediation/plans/PL-0101/approve', headers: { 'idempotency-key': 'abcdefgh1234' }, body: { plan_hash: plan.plan_hash, reason: 'verified' } });
    expect(again).toEqual(r);
    m.completeApproved('INC-0002', 'PL-0101');
    expect(events.length).toBeGreaterThanOrEqual(4);
    const sv = component('StreamEvent');
    for (const e of events) expect(valid(sv, e.payload), JSON.stringify(e.payload)).toEqual([]);
    expect(valid(S('execution'), m.incidents['INC-0002'].remediation.executions[0])).toEqual([]);
  });

  it('SSE replay: eventsAfter(id) returns only newer events (Last-Event-ID)', () => {
    const m = createMock();
    const a = m.emit('service.health', { service: 'api' });
    const b = m.emit('service.health', { service: 'redis' });
    expect(m.eventsAfter(a.id).map((e) => e.id)).toEqual([b.id]);
    expect(m.eventsAfter(b.id)).toEqual([]);
  });
});
