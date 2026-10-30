// Optional end-to-end check of the REAL static export behind REAL nginx with the committed config:
// nginx serves frontend/out, proxies /api/ to the mock server (cookie login, SSE), and Chromium (Playwright)
// loads every route while we assert: security headers present, no CSP violations, the page hydrates and works,
// the SSE connection opens through nginx and reconnects after the stream is dropped, an injected inline
// script is blocked by the CSP, and the approve flow works. Needs: nginx, a global `playwright`, `npm run build`.
//   node scripts/verify-nginx-e2e.mjs
import { spawn, spawnSync } from 'node:child_process';
import { installMimeTypes } from './check-nginx.mjs';
import { cpSync, existsSync, mkdirSync, mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const NGINX_DIR = join(root, '..', 'infra', 'nginx');
const MOCK_PORT = 18080, WEB_PORT = 18088;
const results = [];
const check = (name, ok, extra = '') => { results.push({ name, ok: !!ok }); console.log(`${ok ? 'PASS' : 'FAIL'}: ${name}${extra ? ` (${extra})` : ''}`); };

if (spawnSync('nginx', ['-v']).error) { console.log('skipped: nginx not installed'); process.exit(0); }
let chromium;
try { ({ chromium } = createRequire(import.meta.url)('playwright')); } catch { console.log('skipped: playwright not available'); process.exit(0); }
if (!existsSync(join(root, 'out', 'index.html'))) { console.error('run `npm run build` first'); process.exit(1); }

const tmp = mkdtempSync(join(tmpdir(), 'cd-e2e-'));
const procs = [];
try {
  mkdirSync(join(tmp, 'cloud-doctor'));
  installMimeTypes(tmp);
  const rendered = spawnSync(process.execPath, [join(here, 'render-nginx.mjs'), '--upstream', `127.0.0.1:${MOCK_PORT}`, '--listen', `127.0.0.1:${WEB_PORT}`, '--root', join(root, 'out')], { encoding: 'utf8' }).stdout;
  writeFileSync(join(tmp, 'cloud-doctor', 'cloud-doctor.conf'), rendered);
  for (const f of ['security-headers.inc', 'csp-script-hashes.conf']) cpSync(join(NGINX_DIR, f), join(tmp, 'cloud-doctor', f));
  writeFileSync(join(tmp, 'nginx.conf'), `daemon off;\nworker_processes 1;\npid ${tmp}/n.pid;\nerror_log ${tmp}/error.log;\nevents {}\nhttp {\n access_log off;\n client_body_temp_path ${tmp}/b; proxy_temp_path ${tmp}/p; fastcgi_temp_path ${tmp}/f; uwsgi_temp_path ${tmp}/u; scgi_temp_path ${tmp}/s;\n include cloud-doctor/cloud-doctor.conf;\n}\n`);
  procs.push(spawn(process.execPath, [join(root, 'mock', 'server.mjs')], { env: { ...process.env, PORT: String(MOCK_PORT) }, stdio: 'ignore' }));
  procs.push(spawn('nginx', ['-p', tmp, '-c', join(tmp, 'nginx.conf'), '-e', join(tmp, 'error.log')], { stdio: 'ignore' }));
  await new Promise((r) => setTimeout(r, 1500));

  const base = `http://127.0.0.1:${WEB_PORT}`;
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const violations = [], errors = [];
  await page.addInitScript(() => { window.__csp = []; document.addEventListener('securitypolicyviolation', (e) => window.__csp.push(`${e.violatedDirective} ${e.blockedURI}`)); });
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
  page.on('console', (m) => { if (m.type() === 'error' && !/401|Unauthorized/.test(m.text())) errors.push(m.text().slice(0, 200)); if (/Content Security Policy|Refused to/i.test(m.text())) violations.push(m.text().slice(0, 200)); });

  const first = await page.goto(`${base}/`);
  const h = first.headers();
  check('CSP header present, no unsafe-inline in script-src/style-src', h['content-security-policy'] && !/unsafe-inline/.test(h['content-security-policy']) && /frame-ancestors 'none'/.test(h['content-security-policy']));
  check('X-Content-Type-Options / Referrer-Policy / Permissions-Policy present', h['x-content-type-options'] === 'nosniff' && h['referrer-policy'] && h['permissions-policy']);
  await page.waitForURL('**/login/', { timeout: 8000 }).catch(async () => { console.log('DEBUG url', page.url(), 'csp', JSON.stringify(await page.evaluate(() => window.__csp)), 'errors', JSON.stringify(errors), JSON.stringify(violations)); throw new Error('no redirect to /login/'); });
  await page.fill('input[type=password]', 'e2e-token-1234');
  await page.click('button[type=submit]');
  await page.waitForSelector('[data-testid=svc-api]');
  check('login through nginx proxy + overview hydrates under the CSP', true);
  await page.waitForSelector('[data-conn=open]', { timeout: 10000 });
  check('SSE connection opens through nginx (buffering off)', true);

  await fetch(`http://127.0.0.1:${MOCK_PORT}/__mock/drop-stream`, { method: 'POST' });
  await page.waitForSelector('[data-conn=reconnecting]', { timeout: 10000 }).catch(() => undefined);
  await page.waitForSelector('[data-conn=open]', { timeout: 20000 });
  check('SSE reconnects after the stream is dropped', true);

  for (const u of ['/topology/', '/incidents/', '/incidents/view/?id=INC-0002&tab=evidence', '/incidents/view/?id=INC-0003&tab=remediation', '/incidents/view/?id=INC-0005&tab=verification', '/incidents/view/?id=INC-0001&tab=report', '/services/view/?name=api', '/audit/?incident=INC-0003']) {
    const r = await page.goto(`${base}${u}`);
    await page.waitForSelector('h1');
    await page.waitForTimeout(700);
    check(`route ${u} -> ${r.status()} with headers`, r.status() === 200 && !!r.headers()['content-security-policy']);
  }
  const body = await page.goto(`${base}/incidents/view/?id=INC-0002&tab=evidence`).then(() => page.waitForSelector('[data-testid=ev-EV-103]')).then(() => page.evaluate(() => ({ scripts: document.querySelectorAll('main script').length, imgs: document.querySelectorAll('main img').length, text: document.querySelector('[data-testid=ev-EV-103]').textContent })));
  check('hostile evidence is inert text under the real CSP', body.scripts === 0 && body.imgs === 0 && body.text.includes('<script>alert(1)</script>'));
  const injected = await page.evaluate(() => { window.__x = 0; const s = document.createElement('script'); s.textContent = 'window.__x = 1'; document.head.appendChild(s); return window.__x; });
  check('an injected inline script is blocked by the CSP', injected === 0);
  const seen = await page.evaluate(() => window.__csp);
  check('exactly the deliberate violation was reported (nothing from the app itself)', seen.length === 1 && /script-src/.test(seen[0]), JSON.stringify(seen));

  await page.goto(`${base}/incidents/view/?id=INC-0002&tab=remediation`);
  await page.fill('textarea', 'e2e approval reason');
  await page.click('button:has-text("Approve plan PL-0101")');
  await page.waitForSelector('text=Approved. Decision', { timeout: 8000 }).catch(async () => { console.log('DEBUG approval panel:', await page.locator('.approval').innerText().catch(() => 'n/a')); throw new Error('approve failed'); });
  check('approve flow works end to end through nginx', true);

  const notFound = await page.goto(`${base}/nope/`);
  check('unknown path gives the 404 page with headers', notFound.status() === 404 && !!notFound.headers()['content-security-policy']);
  const dot = await fetch(`${base}/.env`);
  check('dotfiles are not served', dot.status === 404);
  check('no console errors / page errors (other than the deliberate CSP block and the deliberate 404)', errors.filter((e) => !/Content Security Policy|Refused to execute|status of 404/i.test(e)).length === 0, errors.join(' | ').slice(0, 300));
  await browser.close();
} finally {
  for (const p of procs) p.kill('SIGTERM');
  await new Promise((r) => setTimeout(r, 300));
  rmSync(tmp, { recursive: true, force: true });
}
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
