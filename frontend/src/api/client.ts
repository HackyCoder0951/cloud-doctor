// Small fetch client for the Python API (contracts/openapi.yaml). No business logic lives here.
//  - credentials: 'include' so the HttpOnly session cookie set by the API is sent;
//  - every POST carries a fresh (or caller-supplied) Idempotency-Key;
//  - failures become ApiError carrying only a status-derived message and sanitised ids; the raw
//    server message/body is never exposed to the UI (it could contain internals or hostile text).
import type {
  AuditResponse,
  Decision,
  Diagnosis,
  Evidence,
  Incident,
  IncidentState,
  LogResponse,
  MetricName,
  MetricSeries,
  Remediation,
  Report,
  SelfStatus,
  ServiceHealth,
  TimelineEvent,
  Topology,
  Verification,
} from './types';
import { parseCodeAnalysis, type CodeAnalysis } from '@/lib/code-analysis';

export const API_BASE: string = (process.env.NEXT_PUBLIC_API_BASE ?? '/api/v1').replace(/\/+$/, '');

export type ApiErrorKind = 'unauthenticated' | 'forbidden' | 'not_found' | 'conflict' | 'rate_limited' | 'invalid' | 'unavailable' | 'network' | 'unknown';

const KIND_MESSAGE: Record<ApiErrorKind, string> = {
  unauthenticated: 'Your session is missing or expired. Please sign in again.',
  forbidden: 'The API refused this action (authorization or policy).',
  not_found: 'The requested item was not found.',
  conflict: 'The state changed or the action was already applied. Reload and check.',
  rate_limited: 'Too many requests. Wait a moment and try again.',
  invalid: 'The API rejected the request as invalid.',
  unavailable: 'The API or one of its safety dependencies is unavailable (fail closed).',
  network: 'The API could not be reached.',
  unknown: 'Unexpected API error.',
};

function kindFor(status: number): ApiErrorKind {
  if (status === 401) return 'unauthenticated';
  if (status === 403) return 'forbidden';
  if (status === 404) return 'not_found';
  if (status === 409) return 'conflict';
  if (status === 429) return 'rate_limited';
  if (status === 400 || status === 422) return 'invalid';
  if (status === 502 || status === 503 || status === 504) return 'unavailable';
  return 'unknown';
}

const CODE_RE = /^[a-z][a-z0-9_.-]{0,39}$/;
const RULE_RE = /^[A-Za-z][A-Za-z0-9-]{0,23}$/;

export class ApiError extends Error {
  readonly status: number;
  readonly kind: ApiErrorKind;
  /** Short machine code from the API, only if it matches a strict pattern. */
  readonly code?: string;
  /** Policy rule ids (e.g. I-03), only entries matching a strict pattern. */
  readonly ruleIds: string[];
  constructor(status: number, kind: ApiErrorKind, code?: string, ruleIds: string[] = []) {
    super(KIND_MESSAGE[kind]);
    this.name = 'ApiError';
    this.status = status;
    this.kind = kind;
    this.code = code;
    this.ruleIds = ruleIds;
  }
}

async function toApiError(res: Response): Promise<ApiError> {
  let code: string | undefined;
  let ruleIds: string[] = [];
  try {
    const body: unknown = await res.json();
    if (body && typeof body === 'object') {
      const b = body as Record<string, unknown>;
      if (typeof b.code === 'string' && CODE_RE.test(b.code)) code = b.code;
      if (Array.isArray(b.rule_ids)) {
        ruleIds = b.rule_ids.filter((r): r is string => typeof r === 'string' && RULE_RE.test(r)).slice(0, 12);
      }
    }
  } catch {
    /* body is not JSON: ignore, the status alone drives the message */
  }
  return new ApiError(res.status, kindFor(res.status), code, ruleIds);
}

/** Message safe to display for any thrown value. */
export function describeError(e: unknown): string {
  if (e instanceof ApiError) {
    const extra = [e.code, ...e.ruleIds].filter(Boolean).join(', ');
    return extra ? `${e.message} (${extra})` : e.message;
  }
  return KIND_MESSAGE.unknown;
}

/** 32 URL-safe chars; satisfies ^[A-Za-z0-9_-]{8,64}$. */
export function newIdempotencyKey(): string {
  const c = globalThis.crypto;
  if (c?.randomUUID) return c.randomUUID().replace(/-/g, '');
  const bytes = new Uint8Array(16);
  if (c?.getRandomValues) c.getRandomValues(bytes);
  else throw new Error('no secure random source available');
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

type Listener = () => void;
const unauthorizedListeners = new Set<Listener>();
/** The shell subscribes to redirect to the login page on any 401. UX only: the API enforces auth. */
export function onUnauthorized(fn: Listener): () => void {
  unauthorizedListeners.add(fn);
  return () => unauthorizedListeners.delete(fn);
}

type Query = Record<string, string | number | undefined>;

function buildUrl(path: string, query?: Query): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query ?? {})) if (v !== undefined) qs.set(k, String(v));
  const s = qs.toString();
  return `${API_BASE}${path}${s ? `?${s}` : ''}`;
}

async function request(method: 'GET' | 'POST', path: string, opts: { query?: Query; body?: unknown; accept?: string; idempotencyKey?: string; signal?: AbortSignal } = {}): Promise<Response> {
  const headers: Record<string, string> = { Accept: opts.accept ?? 'application/json' };
  if (method === 'POST') {
    headers['Idempotency-Key'] = opts.idempotencyKey ?? newIdempotencyKey();
    if (opts.body !== undefined) headers['Content-Type'] = 'application/json';
  }
  let res: Response;
  try {
    res = await fetch(buildUrl(path, opts.query), {
      method,
      headers,
      credentials: 'include',
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      signal: opts.signal,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    throw new ApiError(0, 'network');
  }
  if (!res.ok) {
    const err = await toApiError(res);
    if (err.kind === 'unauthenticated' && !path.startsWith('/auth/login')) unauthorizedListeners.forEach((f) => f());
    throw err;
  }
  return res;
}

async function getJson<T>(path: string, query?: Query, signal?: AbortSignal): Promise<T> {
  const res = await request('GET', path, { query, signal });
  try {
    return (await res.json()) as T;
  } catch {
    throw new ApiError(res.status, 'unknown');
  }
}

const enc = encodeURIComponent;

export const api = {
  login: (token: string) => request('POST', '/auth/login', { body: { token } }).then(() => undefined),
  logout: () => request('POST', '/auth/logout').then(() => undefined),
  listServices: (signal?: AbortSignal) => getJson<ServiceHealth[]>('/services', undefined, signal),
  getServiceHealth: (service: string) => getJson<ServiceHealth>(`/services/${enc(service)}/health`),
  getServiceMetric: (service: string, name: MetricName, sinceSeconds = 600) =>
    getJson<MetricSeries>(`/services/${enc(service)}/metrics`, { name, since_seconds: sinceSeconds }),
  getServiceLogs: (service: string, sinceSeconds = 300, limit = 100) =>
    getJson<LogResponse>(`/services/${enc(service)}/logs`, { since_seconds: sinceSeconds, limit }),
  getTopology: () => getJson<Topology>('/topology'),
  listIncidents: (state?: IncidentState, limit = 50) => getJson<Incident[]>('/incidents', { state, limit }),
  getIncident: (id: string) => getJson<Incident>(`/incidents/${enc(id)}`),
  getTimeline: (id: string) => getJson<TimelineEvent[]>(`/incidents/${enc(id)}/timeline`),
  getEvidence: (id: string) => getJson<Evidence[]>(`/incidents/${enc(id)}/evidence`),
  getDiagnosis: (id: string) => getJson<Diagnosis>(`/incidents/${enc(id)}/diagnosis`),
  rediagnose: (id: string, idempotencyKey?: string) =>
    request('POST', `/incidents/${enc(id)}/diagnose`, { idempotencyKey }).then(() => undefined),
  getRemediation: (id: string) => getJson<Remediation>(`/incidents/${enc(id)}/remediation`),
  approvePlan: (id: string, plan: string, body: { plan_hash: string; reason: string }, idempotencyKey?: string) =>
    request('POST', `/incidents/${enc(id)}/remediation/plans/${enc(plan)}/approve`, { body, idempotencyKey }).then((r) => r.json() as Promise<Decision>),
  rejectPlan: (id: string, plan: string, body: { reason: string }, idempotencyKey?: string) =>
    request('POST', `/incidents/${enc(id)}/remediation/plans/${enc(plan)}/reject`, { body, idempotencyKey }).then(() => undefined),
  getVerification: (id: string) => getJson<Verification[]>(`/incidents/${enc(id)}/verification`),
  getReport: (id: string) => getJson<Report>(`/incidents/${enc(id)}/report`),
  getReportMarkdown: async (id: string): Promise<string> => (await request('GET', `/incidents/${enc(id)}/report`, { accept: 'text/markdown' })).text(),
  listAudit: (opts: { incident?: string; afterSeq?: number; limit?: number } = {}) =>
    getJson<AuditResponse>('/audit', { incident: opts.incident, after_seq: opts.afterSeq, limit: opts.limit }),
  getStatus: () => getJson<SelfStatus>('/status'),
  /** Proposed endpoint (frontend-4). Resolves to null when the backend does not provide it (404): "not available", never an empty success. */
  getCodeAnalysis: async (id: string): Promise<CodeAnalysis | null> => {
    try {
      return parseCodeAnalysis(await getJson<unknown>(`/incidents/${enc(id)}/code-analysis`));
    } catch (e) {
      if (e instanceof ApiError && e.kind === 'not_found') return null;
      throw e;
    }
  },
};
