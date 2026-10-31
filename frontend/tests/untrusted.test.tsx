import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { DEFAULT_MAX, jsonText, safeText, Untrusted } from '@/lib/untrusted';

const PAYLOADS = [
  '<script>alert(1)</script>',
  '<img src=x onerror=alert(1)>',
  'javascript:alert(document.cookie)',
  '"><svg onload=alert(1)>',
  '<a href="javascript:alert(1)">click</a>',
];

describe('Untrusted rendering', () => {
  it.each(PAYLOADS)('renders %s as inert text', (p) => {
    const { container } = render(<Untrusted value={p} />);
    expect(container.textContent).toBe(p);
    expect(container.querySelector('script, img, svg, a, iframe')).toBeNull();
    expect(container.querySelector('[onerror], [onload], [onclick], [href], [src]')).toBeNull();
    expect(container.innerHTML).not.toContain('<script');
  });

  it('truncates very long values and reports the original length', () => {
    const long = 'A'.repeat(100_000);
    const { container } = render(<Untrusted value={long} />);
    expect((container.textContent ?? '').length).toBeLessThan(DEFAULT_MAX + 100);
    expect(container.textContent).toContain('truncated, 100000 chars');
  });

  it('makes control and bidi-override characters visible', () => {
    const s = safeText('a‮b\u0000c\u001b[31m');
    expect(s.text).toContain('\\u202e');
    expect(s.text).toContain('\\u0000');
    expect(s.text).toContain('\\u001b');
    expect(s.text).not.toMatch(/[‮\u0000\u001b]/);
  });

  it('tolerates null, undefined and non-strings', () => {
    expect(safeText(null).text).toBe('');
    expect(safeText(undefined).text).toBe('');
    expect(safeText(42).text).toBe('42');
  });

  it('serialises untrusted objects as truncated text', () => {
    const j = jsonText({ line: '<script>alert(1)</script>'.repeat(1000) }, 500);
    expect(j.truncated).toBe(true);
    expect(j.text.length).toBe(500);
  });
});
