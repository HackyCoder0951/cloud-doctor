// XSS-inert rendering: hostile strings placed in EVERY free-text field the API can return must
// show up as visible text, never as elements, attributes or links.
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createMock, type MockRequest } from '../mock/router.mjs';
import { installFetch } from './helpers';
import { nav, setupNav } from './nav-mock';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: (u: string) => nav.replace(u), push: (u: string) => nav.push(u) }),
  usePathname: () => nav.path,
  useSearchParams: () => nav.params,
}));

import { IncidentPage, ServicePage } from '@/components/routes';
import { Overview } from '@/components/views/Overview';

const PAYLOADS = ['<script>alert(1)</script>', '<img src=x onerror=alert(1)>', 'javascript:alert(1)', '"><svg onload=alert(1)>', '<a href="javascript:alert(1)">x</a>', `${'Z'.repeat(60_000)}`];
const HOSTILE = PAYLOADS.join(' | ');

const dangerous = (root: HTMLElement) => root.querySelectorAll('script, iframe, object, embed, img, form img, [onerror], [onload], [onclick], [onfocus], a[href^="javascript" i], [src^="javascript" i]');

/** Walk a JSON value and replace every string except ids/enums with hostile text, keyed by field name. */
const TEXT_FIELDS = new Set(['summary', 'text', 'description', 'rationale', 'detail', 'line', 'query', 'cause_id', 'engine_version', 'version']);
function poison(v: unknown, key = ''): unknown {
  if (Array.isArray(v)) return v.map((x) => (typeof x === 'string' && ['symptoms', 'reasons', 'alternatives', 'unknowns', 'limitations', 'confidence_basis'].includes(key) ? HOSTILE : poison(x, key)));
  if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, poison(x, k)]));
  if (typeof v === 'string' && TEXT_FIELDS.has(key)) return HOSTILE;
  return v;
}

function hostileFetch() {
  const mock = createMock();
  return installFetch(mock, (req: MockRequest) => {
    if (req.method !== 'GET' || req.path === '/status') return undefined;
    const r = mock.handle(req);
    return r.body !== undefined && r.body !== null ? { status: r.status, body: poison(r.body) } : r;
  });
}

beforeEach(() => setupNav());

describe.each([
  ['timeline'], ['evidence'], ['diagnosis'], ['remediation'], ['verification'], ['report'],
])('hostile text in the %s tab', (tab) => {
  it('is rendered as inert, truncated text', async () => {
    hostileFetch();
    setupNav('/incidents/view/', `id=${tab === 'remediation' ? 'INC-0003' : 'INC-0001'}&tab=${tab}`);
    const { container } = render(<IncidentPage />);
    await screen.findByRole('tabpanel');
    await vi.waitFor(() => expect(container.querySelectorAll('[data-untrusted]').length).toBeGreaterThan(2));
    expect(dangerous(container)).toHaveLength(0);
    // the payload is visible as text...
    expect(container.textContent).toContain('<script>alert(1)</script>');
    expect(container.textContent).toContain('javascript:alert(1)');
    // ...and very long strings are cut with a visible marker instead of flooding the page
    expect(container.textContent).toContain('truncated');
    expect(container.textContent!.length).toBeLessThan(120_000);
    expect(container.querySelectorAll('svg').length).toBe(0);
  });
});

describe('hostile text elsewhere', () => {
  it('incident header symptoms', async () => {
    hostileFetch();
    setupNav('/incidents/view/', 'id=INC-0002&tab=timeline');
    const { container } = render(<IncidentPage />);
    await screen.findByText(/Services:/);
    await vi.waitFor(() => expect(container.textContent).toContain('<script>alert(1)</script>'));
    expect(dangerous(container)).toHaveLength(0);
  });

  it('service logs panel', async () => {
    hostileFetch();
    setupNav('/services/view/', 'name=api');
    const { container } = render(<ServicePage />);
    const logs = await screen.findByTestId('loglines');
    expect(logs.textContent).toContain('<img src=x onerror=alert(1)>');
    expect(dangerous(container).length).toBe(0);
    expect(logs.textContent).toContain('truncated');
  });

  it('overview cards (names/kinds are plain text, links only for valid ids)', async () => {
    const mock = createMock();
    installFetch(mock, (req) => {
      if (req.path === '/services') {
        const base = mock.handle(req).body as Array<Record<string, unknown>>;
        return { status: 200, body: [...base, { name: '<img src=x onerror=alert(1)>', kind: '<script>alert(1)</script>', state: 'HEALTHY', missing_signal_state: 'none', updated_at: '2026-11-02T09:00:00Z', open_incident_ids: ['javascript:alert(1)', 'INC-0001'] }] };
      }
      return undefined;
    });
    const { container } = render(<Overview />);
    await screen.findByTestId(/svc-<img/);
    expect(dangerous(container)).toHaveLength(0);
    expect(container.querySelectorAll('a[href*="javascript"], a[href*="<"]')).toHaveLength(0);
    expect(container.textContent).toContain('javascript:alert(1)');
  });

  it('evidence links are only created for ids that match the contract pattern', async () => {
    const mock = createMock();
    installFetch(mock, (req) => {
      if (req.path.endsWith('/timeline')) {
        return { status: 200, body: [{ event_id: 'TL-0001', incident_id: 'INC-0001', event_time: '2026-11-02T09:00:00Z', collected_at: '2026-11-02T09:00:01Z', kind: 'note', summary: 'x', evidence_refs: ['EV-001', 'javascript:alert(1)', '"><script>'] }] };
      }
      return undefined;
    });
    setupNav('/incidents/view/', 'id=INC-0001&tab=timeline');
    const { container } = render(<IncidentPage />);
    await screen.findByTestId('tl-TL-0001');
    expect(container.querySelectorAll('.evlink')).toHaveLength(1);
    expect(dangerous(container)).toHaveLength(0);
    expect(screen.getByTestId('tl-TL-0001')).toHaveTextContent('javascript:alert(1)');
  });
});
