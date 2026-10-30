// Fails (exit 1) if the UI source uses an API that could turn untrusted text into markup or code.
// TM-16: evidence, logs and error text are always rendered as React text nodes. Runs as `prebuild`,
// in `npm run ci` and from tests/forbidden-apis.test.ts (which also self-tests the patterns).
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, dirname, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

export const RULES = [
  { id: 'dangerouslySetInnerHTML', re: /dangerouslySetInnerHTML/ },
  { id: 'innerHTML', re: /\binnerHTML\b/ },
  { id: 'outerHTML', re: /\bouterHTML\b/ },
  { id: 'insertAdjacentHTML', re: /insertAdjacent(HTML|Element)/ },
  { id: 'document.write', re: /document\s*\.\s*write(ln)?\s*\(/ },
  { id: 'eval', re: /(^|[^.\w$])eval\s*\(/ },
  { id: 'new Function', re: /new\s+Function\b/ },
  { id: 'Function constructor call', re: /(^|[^.\w$])Function\s*\(/ },
  { id: 'string timers', re: /\bset(Timeout|Interval)\s*\(\s*['"`]/ },
  { id: 'inline event-handler string', re: /\son[a-z]{3,}\s*=\s*["'`]/i },
  { id: 'setAttribute on*', re: /setAttribute\s*\(\s*['"`]on/i },
  { id: 'javascript: URL', re: /['"`]\s*javascript:/i },
  { id: 'srcDoc', re: /\bsrcDoc\b/ },
  { id: 'DOMParser/createContextualFragment', re: /\b(DOMParser|createContextualFragment)\b/ },
  { id: 'inline style attribute', re: /\bstyle\s*=\s*\{/ },
  { id: 'target=_blank without review', re: /target\s*=\s*["']_blank["']/ },
];

const SELF_TEST_EXEMPT = /scan-forbidden/;

export function scanText(text, file = '<memory>') {
  const hits = [];
  text.split('\n').forEach((line, i) => {
    for (const r of RULES) if (r.re.test(line)) hits.push({ file, line: i + 1, rule: r.id, text: line.trim().slice(0, 120) });
  });
  return hits;
}

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.(ts|tsx|js|jsx|mjs|css|html)$/.test(name) && !SELF_TEST_EXEMPT.test(p) && !/schema\.d\.ts$/.test(p)) out.push(p);
  }
  return out;
}

export function scanTree(root) {
  const src = join(root, 'src');
  return walk(src).flatMap((f) => scanText(readFileSync(f, 'utf8'), relative(root, f)));
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const root = join(dirname(fileURLToPath(import.meta.url)), '..');
  const hits = scanTree(root);
  if (hits.length) {
    for (const h of hits) console.error(`FORBIDDEN ${h.rule}: ${h.file}:${h.line}: ${h.text}`);
    process.exit(1);
  }
  console.log('ok: no forbidden HTML/code-injection APIs in src/');
}
