// Static check of infra/nginx/cloud-doctor.conf (no nginx binary needed) + `nginx -t` when nginx exists.
//   node scripts/check-nginx.mjs [--no-nginx-t]
// Verifies, per effective location (nginx does NOT inherit add_header into a block that has its own):
// CSP (default-src 'self', no unsafe-inline/unsafe-eval in script-src/style-src, frame-ancestors 'none',
// object-src 'none', base-uri), X-Content-Type-Options nosniff, Referrer-Policy, Permissions-Policy, all `always`;
// try_files for the static routes; /api/ proxy with proxy_buffering off and a long read timeout; and that
// the generated CSP script hashes match the current static export (when frontend/out exists).
import { spawnSync } from 'node:child_process';
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { collectHashes, OUT } from './gen-csp-hashes.mjs';

const here = dirname(fileURLToPath(import.meta.url));
export const NGINX_DIR = join(here, '..', '..', 'infra', 'nginx');

// ---- tiny nginx config parser -------------------------------------------------------------
function tokenize(text) {
  const toks = [];
  let i = 0;
  while (i < text.length) {
    const c = text[i];
    if (/\s/.test(c)) { i++; continue; }
    if (c === '#') { while (i < text.length && text[i] !== '\n') i++; continue; }
    if (c === '{' || c === '}' || c === ';') { toks.push({ t: c }); i++; continue; }
    if (c === '"' || c === "'") {
      let j = i + 1, s = '';
      while (j < text.length && text[j] !== c) { if (text[j] === '\\') j++; s += text[j]; j++; }
      toks.push({ t: 'w', v: s, quoted: true }); i = j + 1; continue;
    }
    let j = i, s = '';
    while (j < text.length && !/[\s{};]/.test(text[j])) { s += text[j]; j++; }
    toks.push({ t: 'w', v: s }); i = j;
  }
  return toks;
}

export function parse(text) {
  const toks = tokenize(text);
  let p = 0;
  function block() {
    const out = [];
    while (p < toks.length && toks[p].t !== '}') {
      const args = [];
      while (p < toks.length && toks[p].t === 'w') args.push(toks[p++].v);
      if (toks[p]?.t === ';') { p++; out.push({ name: args[0], args: args.slice(1) }); }
      else if (toks[p]?.t === '{') { p++; const children = block(); p++; out.push({ name: args[0], args: args.slice(1), children }); }
      else throw new Error('syntax error near token ' + p);
    }
    return out;
  }
  return block();
}

/** Expands `include cloud-doctor/<file>` using `read(file)`; other includes are left alone. */
function expand(nodes, read, problems) {
  const out = [];
  for (const n of nodes) {
    if (n.name === 'include') {
      const m = /^cloud-doctor\/(.+)$/.exec(n.args[0] ?? '');
      if (!m) { out.push(n); continue; } // system includes such as mime.types are not ours to read
      const text = read(m[1]);
      if (text === null || text === undefined) { problems.push(`include ${n.args[0]} cannot be read`); continue; }
      out.push(...expand(parse(text), read, problems));
    } else out.push({ ...n, children: n.children ? expand(n.children, read, problems) : undefined });
  }
  return out;
}

const find = (nodes, name) => nodes.filter((n) => n.name === name);
const headersOf = (nodes) => new Map(find(nodes, 'add_header').map((h) => [h.args[0].toLowerCase(), h.args.slice(1)]));

export function parseCsp(value) {
  const d = new Map();
  for (const part of value.split(';')) {
    const w = part.trim().split(/\s+/).filter(Boolean);
    if (w.length) d.set(w[0].toLowerCase(), w.slice(1));
  }
  return d;
}

function checkCsp(csp, where, problems, hashVar) {
  const d = parseCsp(csp);
  const bad = (m) => problems.push(`${where}: CSP ${m}`);
  const forbid = ['\'unsafe-inline\'', '\'unsafe-eval\'', '*', 'data:', 'https:', 'http:', 'blob:'];
  if (!(d.get('default-src') ?? []).includes("'self'")) bad("default-src must include 'self'");
  const script = d.get('script-src');
  if (!script) bad('script-src missing');
  else {
    if (!script.includes("'self'")) bad("script-src must include 'self'");
    for (const f of forbid) if (script.includes(f)) bad(`script-src must not contain ${f}`);
    for (const w of script) if (!(w === "'self'" || /^'sha256-[A-Za-z0-9+/=]{44}'$/.test(w) || w === hashVar)) bad(`script-src has unexpected source ${w}`);
  }
  const style = d.get('style-src');
  if (!style) bad('style-src missing');
  else for (const f of forbid) if (style.includes(f)) bad(`style-src must not contain ${f}`);
  if (!(d.get('frame-ancestors') ?? []).includes("'none'")) bad("frame-ancestors must be 'none'");
  if (!(d.get('object-src') ?? []).includes("'none'")) bad("object-src must be 'none'");
  if (!d.has('base-uri')) bad('base-uri missing');
  if (!d.has('connect-src')) bad('connect-src missing');
  if (!d.has('form-action')) bad('form-action missing');
  for (const [k, v] of d) for (const w of v) if (w.startsWith('$') && w !== hashVar) bad(`${k} uses unknown variable ${w}`);
}

function checkHeaders(h, where, problems, hashVar) {
  const need = (name) => {
    const v = h.get(name);
    if (!v) { problems.push(`${where}: missing header ${name}`); return null; }
    if (!v.slice(1).includes('always')) problems.push(`${where}: header ${name} must use "always"`);
    return v[0];
  };
  const csp = need('content-security-policy');
  if (csp !== null) checkCsp(csp, where, problems, hashVar);
  const xcto = need('x-content-type-options');
  if (xcto !== null && xcto.toLowerCase() !== 'nosniff') problems.push(`${where}: X-Content-Type-Options must be nosniff`);
  const rp = need('referrer-policy');
  if (rp !== null && !/^(no-referrer|same-origin|strict-origin|strict-origin-when-cross-origin)$/.test(rp)) problems.push(`${where}: weak Referrer-Policy ${rp}`);
  const pp = need('permissions-policy');
  if (pp !== null && !/camera=\(\)/.test(pp)) problems.push(`${where}: Permissions-Policy should disable camera`);
}

const seconds = (s) => { const m = /^(\d+)(ms|s|m|h|d)?$/.exec(s ?? ''); return m ? Number(m[1]) * ({ ms: 0.001, s: 1, m: 60, h: 3600, d: 86400 }[m[2] ?? 's']) : NaN; };

/** read(name) returns the text of a file inside infra/nginx or null. outDir: static export to compare hashes with. */
export function checkConfig({ read, outDir }) {
  const problems = [];
  const mainText = read('cloud-doctor.conf');
  if (mainText === null) return ['cloud-doctor.conf is missing'];
  let top;
  try { top = expand(parse(mainText), read, problems); } catch (e) { return [`cloud-doctor.conf does not parse: ${e.message}`]; }
  const hashVar = '$cd_script_hashes';

  const upstream = find(top, 'upstream').find((u) => u.args[0] === 'cd_api');
  if (!upstream) problems.push('upstream cd_api missing');
  else if (!find(upstream.children, 'server').some((s) => /^[\w.-]+:\d+$/.test(s.args[0] ?? ''))) problems.push('upstream cd_api has no host:port server');

  const server = find(top, 'server')[0];
  if (!server) return [...problems, 'server block missing'];
  const sc = server.children;
  if (find(sc, 'server_tokens')[0]?.args[0] !== 'off') problems.push('server_tokens off is required');
  if (!find(sc, 'root').length) problems.push('root is missing');
  if (find(sc, 'autoindex').some((a) => a.args[0] === 'on')) problems.push('autoindex must not be on');
  if (!find(sc, 'client_max_body_size').length) problems.push('client_max_body_size should be limited');
  const setHashes = find(sc, 'set').find((s) => s.args[0] === hashVar);
  if (!setHashes) problems.push(`${hashVar} is not defined (csp-script-hashes.conf not included?)`);

  const serverHeaders = headersOf(sc);
  const locations = find(sc, 'location');
  if (!locations.length) problems.push('no location blocks');
  for (const loc of locations) {
    const name = `location ${loc.args.join(' ')}`;
    const own = headersOf(loc.children);
    const effective = own.size ? own : serverHeaders; // nginx: add_header is inherited only if the block has none
    checkHeaders(effective, name, problems, hashVar);
  }

  const root = locations.find((l) => l.args.join(' ') === '/');
  if (!root || !find(root.children, 'try_files').length) problems.push('location / needs try_files');
  else if (!find(root.children, 'try_files')[0].args.includes('=404') && !find(root.children, 'try_files')[0].args.some((a) => a.startsWith('/'))) problems.push('try_files needs a final fallback');

  const api = locations.find((l) => l.args.join(' ') === '/api/');
  if (!api) problems.push('location /api/ missing');
  else {
    const c = api.children;
    if (find(c, 'proxy_pass')[0]?.args[0] !== 'http://cd_api') problems.push('/api/ must proxy_pass http://cd_api (URI passed unchanged)');
    if (find(c, 'proxy_buffering')[0]?.args[0] !== 'off') problems.push('/api/ needs proxy_buffering off (SSE)');
    if (!(seconds(find(c, 'proxy_read_timeout')[0]?.args[0]) >= 300)) problems.push('/api/ needs proxy_read_timeout >= 300s (SSE)');
    if (find(c, 'proxy_http_version')[0]?.args[0] !== '1.1') problems.push('/api/ needs proxy_http_version 1.1');
    if (!find(c, 'proxy_set_header').some((h) => h.args[0].toLowerCase() === 'connection' && h.args[1] === '')) problems.push('/api/ must clear the Connection header (keepalive upstream)');
  }

  if (setHashes) {
    const listed = new Set((setHashes.args[1] ?? '').split(/\s+/).filter(Boolean));
    if (listed.size === 0) problems.push('csp-script-hashes.conf lists no hashes');
    if (outDir && existsSync(outDir)) {
      const missing = collectHashes(outDir).filter((h) => !listed.has(h));
      if (missing.length) problems.push(`csp-script-hashes.conf is stale: ${missing.length} inline script hash(es) of the current export are not allow-listed (run npm run build)`);
    }
  }
  return problems;
}

const MINIMAL_MIME = 'types {\n  text/html html;\n  text/css css;\n  application/javascript js;\n  application/json json;\n  text/plain txt;\n}\n';
/** Copies the system mime.types next to a temporary nginx prefix (or writes a minimal one). */
export function installMimeTypes(prefix) {
  for (const c of ['/etc/nginx/mime.types', '/usr/local/etc/nginx/mime.types', '/opt/homebrew/etc/nginx/mime.types']) if (existsSync(c)) return cpSync(c, join(prefix, 'mime.types'));
  writeFileSync(join(prefix, 'mime.types'), MINIMAL_MIME);
}

export function runNginxT(dir = NGINX_DIR) {
  const v = spawnSync('nginx', ['-v'], { encoding: 'utf8' });
  if (v.error || v.status !== 0) return { ran: false, ok: true, output: 'nginx binary not found: skipped `nginx -t`' };
  const tmp = mkdtempSync(join(tmpdir(), 'cd-nginx-'));
  try {
    mkdirSync(join(tmp, 'cloud-doctor'));
    installMimeTypes(tmp);
    for (const f of ['cloud-doctor.conf', 'security-headers.inc', 'csp-script-hashes.conf']) if (existsSync(join(dir, f))) cpSync(join(dir, f), join(tmp, 'cloud-doctor', f));
    const main = `worker_processes 1;\npid ${tmp}/nginx.pid;\nerror_log ${tmp}/error.log;\nevents {}\nhttp {\n  access_log off;\n  client_body_temp_path ${tmp}/b; proxy_temp_path ${tmp}/p; fastcgi_temp_path ${tmp}/f; uwsgi_temp_path ${tmp}/u; scgi_temp_path ${tmp}/s;\n  include cloud-doctor/cloud-doctor.conf;\n}\n`;
    writeFileSync(join(tmp, 'nginx.conf'), main);
    const r = spawnSync('nginx', ['-t', '-p', tmp, '-c', join(tmp, 'nginx.conf'), '-e', join(tmp, 'error.log')], { encoding: 'utf8' });
    return { ran: true, ok: r.status === 0, output: `${r.stdout}${r.stderr}`.trim(), version: `${v.stderr}${v.stdout}`.trim() };
  } finally { rmSync(tmp, { recursive: true, force: true }); }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const read = (n) => (existsSync(join(NGINX_DIR, n)) ? readFileSync(join(NGINX_DIR, n), 'utf8') : null);
  const problems = checkConfig({ read, outDir: OUT });
  for (const p of problems) console.error(`FAIL: ${p}`);
  if (!existsSync(OUT)) console.log('note: frontend/out not built; CSP hash staleness not checked');
  let ok = problems.length === 0;
  if (ok) console.log('ok: static header/proxy checks passed');
  if (!process.argv.includes('--no-nginx-t')) {
    const t = runNginxT();
    console.log(t.ran ? `${t.ok ? 'ok' : 'FAIL'}: nginx -t (${t.version})\n${t.output}` : t.output);
    ok = ok && t.ok;
  }
  process.exit(ok ? 0 : 1);
}
