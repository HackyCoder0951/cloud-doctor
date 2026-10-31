import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
// @ts-expect-error plain .mjs scripts without types
import { checkConfig, NGINX_DIR, parseCsp, runNginxT } from '../scripts/check-nginx.mjs';
// @ts-expect-error plain .mjs scripts without types
import { inlineScripts, OUT } from '../scripts/gen-csp-hashes.mjs';

const files = (over: Record<string, (s: string) => string> = {}) => (name: string) => {
  const p = join(NGINX_DIR, name);
  if (!existsSync(p)) return null;
  const text = readFileSync(p, 'utf8');
  return over[name] ? over[name](text) : text;
};
const problems = (over: Record<string, (s: string) => string> = {}) => checkConfig({ read: files(over), outDir: undefined }) as string[];

describe('infra/nginx static checker', () => {
  it('passes for the committed configuration', () => {
    expect(problems()).toEqual([]);
  });

  it('also matches the current static export when it is built (hash allow-list is not stale)', () => {
    if (!existsSync(OUT)) return; // `npm run build` not run yet
    expect(checkConfig({ read: files(), outDir: OUT })).toEqual([]);
  });

  it.each([
    ['CSP missing', { 'security-headers.inc': (s: string) => s.replace(/add_header Content-Security-Policy[^\n]*\n/, '') }, /missing header content-security-policy/],
    ["'unsafe-inline' in script-src", { 'security-headers.inc': (s: string) => s.replace("script-src 'self'", "script-src 'self' 'unsafe-inline'") }, /script-src must not contain 'unsafe-inline'/],
    ["'unsafe-eval' in script-src", { 'security-headers.inc': (s: string) => s.replace("script-src 'self'", "script-src 'self' 'unsafe-eval'") }, /unsafe-eval/],
    ["'unsafe-inline' in style-src", { 'security-headers.inc': (s: string) => s.replace("style-src 'self'", "style-src 'self' 'unsafe-inline'") }, /style-src must not contain/],
    ['wildcard script source', { 'security-headers.inc': (s: string) => s.replace("script-src 'self'", "script-src * 'self'") }, /script-src must not contain \*/],
    ['unknown script host', { 'security-headers.inc': (s: string) => s.replace("script-src 'self'", "script-src 'self' cdn.example.com") }, /unexpected source cdn.example.com/],
    ['frame-ancestors dropped', { 'security-headers.inc': (s: string) => s.replace('; frame-ancestors \'none\'', '') }, /frame-ancestors/],
    ['nosniff dropped', { 'security-headers.inc': (s: string) => s.replace(/add_header X-Content-Type-Options[^\n]*\n/, '') }, /x-content-type-options/],
    ['Referrer-Policy dropped', { 'security-headers.inc': (s: string) => s.replace(/add_header Referrer-Policy[^\n]*\n/, '') }, /referrer-policy/],
    ['Permissions-Policy dropped', { 'security-headers.inc': (s: string) => s.replace(/add_header Permissions-Policy[^\n]*\n/, '') }, /permissions-policy/],
    ['"always" dropped', { 'security-headers.inc': (s: string) => s.replace('"nosniff" always', '"nosniff"') }, /must use "always"/],
    ['a location overrides add_header without the include (nginx does not inherit)', { 'cloud-doctor.conf': (s: string) => s.replace(/(location \/ \{[^}]*?)include cloud-doctor\/security-headers\.inc;/, '$1') }, /location \/: missing header/],
    ['proxy_buffering on', { 'cloud-doctor.conf': (s: string) => s.replace('proxy_buffering off;', 'proxy_buffering on;') }, /proxy_buffering off/],
    ['short SSE timeout', { 'cloud-doctor.conf': (s: string) => s.replace('proxy_read_timeout 3600s;', 'proxy_read_timeout 60s;') }, /proxy_read_timeout/],
    ['try_files removed', { 'cloud-doctor.conf': (s: string) => s.replace('try_files $uri $uri/ =404;', '') }, /try_files/],
    ['proxy_pass rewritten', { 'cloud-doctor.conf': (s: string) => s.replace('proxy_pass http://cd_api;', 'proxy_pass http://127.0.0.1:1/;') }, /proxy_pass/],
    ['server_tokens on', { 'cloud-doctor.conf': (s: string) => s.replace('server_tokens off;', 'server_tokens on;') }, /server_tokens/],
    ['hashes include missing', { 'cloud-doctor.conf': (s: string) => s.replace('include cloud-doctor/csp-script-hashes.conf;', '') }, /cd_script_hashes is not defined/],
    ['autoindex on', { 'cloud-doctor.conf': (s: string) => s.replace('index index.html;', 'index index.html;\n    autoindex on;') }, /autoindex/],
  ])('rejects: %s', (_name, over, re) => {
    const p = problems(over as Record<string, (s: string) => string>);
    expect(p.some((x) => (re as RegExp).test(x)), p.join('\n')).toBe(true);
  });

  it('detects a stale hash allow-list against an export', () => {
    if (!existsSync(OUT)) return;
    const stale = { 'csp-script-hashes.conf': (s: string) => s.replace(/'sha256-[^']+'/, "'sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA='") };
    const p = checkConfig({ read: files(stale), outDir: OUT }) as string[];
    expect(p.some((x) => /stale/.test(x))).toBe(true);
  });

  it('parses CSP directives', () => {
    expect(parseCsp("default-src 'self'; script-src 'self' 'sha256-x'").get('script-src')).toEqual(["'self'", "'sha256-x'"]);
  });

  it('extracts only inline scripts for hashing', () => {
    expect(inlineScripts('<script src="/a.js" async></script><script>one()</script><SCRIPT id=x>two()</SCRIPT>')).toEqual(['one()', 'two()']);
  });

  it('nginx -t succeeds when nginx exists (skipped otherwise)', () => {
    const r = runNginxT();
    expect(r.ok, r.output).toBe(true);
  });
});
