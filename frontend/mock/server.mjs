// Plain Node http mock of the Cloud Doctor API (no dependencies).
//   npm run mock            -> http://localhost:8080/api/v1  (PORT / HOST override)
// Auth: POST /auth/login accepts any token of 8+ characters and sets an HttpOnly cd_session cookie.
// SSE:  GET /stream with Last-Event-ID replay and 15 s keep-alive comments.
// Dev helpers (NOT part of the contract): POST /__mock/status {state}, POST /__mock/drop-stream.
import { createServer } from 'node:http';
import { randomBytes } from 'node:crypto';
import { createMock } from './router.mjs';

const PORT = Number(process.env.PORT ?? 8080);
const HOST = process.env.HOST ?? '127.0.0.1';
const PREFIX = '/api/v1';
const mock = createMock();
const sessions = new Set();
const streams = new Set();

function parseCookies(h = '') {
  return Object.fromEntries(h.split(';').map((p) => p.trim().split('=')).filter((p) => p[0]).map(([k, ...v]) => [k, v.join('=')]));
}

function cors(req, res) {
  const origin = req.headers.origin;
  if (origin && /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin)) {
    res.setHeader('Access-Control-Allow-Origin', origin);
    res.setHeader('Access-Control-Allow-Credentials', 'true');
    res.setHeader('Vary', 'Origin');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Idempotency-Key, Accept, Last-Event-ID');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  }
}

function readBody(req) {
  return new Promise((resolve) => {
    const chunks = [];
    let size = 0;
    req.on('data', (c) => { size += c.length; if (size < 100_000) chunks.push(c); });
    req.on('end', () => {
      if (!chunks.length) return resolve(undefined);
      try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf8'))); } catch { resolve({ __invalid: true }); }
    });
  });
}

function send(res, { status, body, text, contentType }) {
  if (text !== undefined) { res.writeHead(status, { 'Content-Type': contentType ?? 'text/plain; charset=utf-8', 'Cache-Control': 'no-store' }); return res.end(text); }
  if (body === null || body === undefined) { res.writeHead(status === 200 ? 204 : status, { 'Cache-Control': 'no-store' }); return res.end(); }
  res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
  return res.end(JSON.stringify(body));
}

function sse(req, res) {
  res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', Connection: 'keep-alive', 'X-Accel-Buffering': 'no' });
  const write = (e) => res.write(`id: ${e.id}\ndata: ${JSON.stringify(e.payload)}\n\n`);
  res.write('retry: 2000\n\n');
  const last = Number(req.headers['last-event-id']);
  if (Number.isInteger(last) && last >= 0) mock.eventsAfter(last).forEach(write);
  else res.write(': connected\n\n');
  const unsub = mock.subscribe(write);
  const ka = setInterval(() => res.write(': keep-alive\n\n'), 15_000);
  const entry = { res };
  streams.add(entry);
  req.on('close', () => { clearInterval(ka); unsub(); streams.delete(entry); });
}

const server = createServer(async (req, res) => {
  cors(req, res);
  if (req.method === 'OPTIONS') { res.writeHead(204); return res.end(); }
  const url = new URL(req.url ?? '/', 'http://mock');

  if (url.pathname.startsWith('/__mock/')) {
    if (req.method !== 'POST') { res.writeHead(405); return res.end(); }
    if (url.pathname === '/__mock/status') {
      const b = await readBody(req);
      if (!['ok', 'degraded', 'fail_closed'].includes(b?.state)) { res.writeHead(422); return res.end(); }
      mock.setStatus(b.state);
      res.writeHead(204); return res.end();
    }
    if (url.pathname === '/__mock/drop-stream') { streams.forEach((s) => s.res.end()); res.writeHead(204); return res.end(); }
    res.writeHead(404); return res.end();
  }

  if (!url.pathname.startsWith(`${PREFIX}/`)) { res.writeHead(404); return res.end(); }
  const path = url.pathname.slice(PREFIX.length);

  if (req.method === 'POST' && path === '/auth/login') {
    const b = await readBody(req);
    if (typeof b?.token !== 'string' || b.token.length < 8 || b.token.length > 256) return send(res, { status: 401, body: { code: 'invalid_token', message: 'invalid token' } });
    const id = randomBytes(16).toString('hex');
    sessions.add(id);
    res.setHeader('Set-Cookie', `cd_session=${id}; HttpOnly; SameSite=Lax; Path=/`);
    res.writeHead(204); return res.end();
  }
  const open = path === '/status';
  const cookie = parseCookies(req.headers.cookie).cd_session;
  if (!open && !(cookie && sessions.has(cookie))) return send(res, { status: 401, body: { code: 'unauthenticated', message: 'login required' } });
  if (req.method === 'POST' && path === '/auth/logout') {
    sessions.delete(cookie);
    res.setHeader('Set-Cookie', 'cd_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0');
    res.writeHead(204); return res.end();
  }
  if (req.method === 'GET' && path === '/stream') return sse(req, res);

  const body = req.method === 'POST' ? await readBody(req) : undefined;
  const result = mock.handle({ method: req.method ?? 'GET', path, query: url.searchParams, headers: req.headers, body });
  send(res, result);
  const m = /^\/incidents\/(INC-\d+)\/remediation\/plans\/(PL-\d+)\/approve$/.exec(path);
  if (m && result.status === 200) setTimeout(() => mock.completeApproved(m[1], m[2]), 2000);
});

// Synthetic live traffic so the UI visibly updates.
const SERVICE_NAMES = ['api', 'worker', 'redis', 'loadgen'];
let tick = 0;
setInterval(() => {
  tick += 1;
  const service = SERVICE_NAMES[tick % SERVICE_NAMES.length];
  mock.emit('service.health', { service, data: { tick } });
  if (tick % 3 === 0) mock.emit('timeline.event', { incident_id: 'INC-0002', service: 'api', data: { summary: `heartbeat ${tick}` } });
}, 4000).unref?.();

server.listen(PORT, HOST, () => console.log(`cloud-doctor mock API on http://${HOST}:${PORT}${PREFIX} (login: any token of 8+ chars)`));
