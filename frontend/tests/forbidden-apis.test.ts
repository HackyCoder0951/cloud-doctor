import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
// @ts-expect-error plain .mjs script without types
import { scanText, scanTree } from '../scripts/scan-forbidden.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');

describe('forbidden API scan (TM-16)', () => {
  it('finds no forbidden HTML/code-injection API in src/', () => {
    expect(scanTree(root)).toEqual([]);
  });

  it.each([
    ['dangerouslySetInnerHTML', '<div dangerouslySetInnerHTML={{ __html: x }} />'],
    ['innerHTML', 'el.innerHTML = x;'],
    ['outerHTML', 'el.outerHTML = x;'],
    ['insertAdjacentHTML', "el.insertAdjacentHTML('beforeend', x)"],
    ['document.write', 'document.write(x)'],
    ['eval', 'const r = eval(x);'],
    ['new Function', "const f = new Function('return 1');"],
    ['string timers', "setTimeout('alert(1)', 10)"],
    ['inline event-handler string', '<button onClick="alert(1)">x</button>'],
    ['setAttribute on*', "el.setAttribute('onclick', x)"],
    ['javascript: URL', "const u = 'javascript:alert(1)';"],
    ['srcDoc', '<iframe srcDoc={x} />'],
    ['inline style attribute', '<div style={{ width: 3 }} />'],
  ])('detects %s (pattern self-test)', (rule, snippet) => {
    expect(scanText(snippet).map((h: { rule: string }) => h.rule)).toContain(rule);
  });

  it('does not flag safe patterns', () => {
    expect(scanText("<button onClick={() => go()}>ok</button>\nconst t = setTimeout(() => x(), 1);\nconst s = textContent;")).toEqual([]);
  });
});
