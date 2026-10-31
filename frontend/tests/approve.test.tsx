import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createMock } from '../mock/router.mjs';
import { installFetch, json } from './helpers';
import { nav, setupNav } from './nav-mock';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: (u: string) => nav.replace(u), push: (u: string) => nav.push(u) }),
  usePathname: () => nav.path,
  useSearchParams: () => nav.params,
}));

import { IncidentPage } from '@/components/routes';

const KEY_RE = /^[A-Za-z0-9_-]{8,64}$/;

async function openRemediation() {
  setupNav('/incidents/view/', 'id=INC-0002&tab=remediation');
  render(<IncidentPage />);
  return screen.findByLabelText('Approval for PL-0101');
}

const type = (text: string) => fireEvent.change(screen.getByLabelText(/Reason/), { target: { value: text } });

beforeEach(() => setupNav());

describe('approve / reject flow (medium-risk plan)', () => {
  it('only offers approval for a medium-risk plan awaiting approval, with the plan hash visible', async () => {
    installFetch();
    await openRemediation();
    const plan = createMock().incidents['INC-0002'].remediation.plans[0];
    expect(screen.getByTestId('plan-hash')).toHaveTextContent(plan.plan_hash);
    expect(screen.getByRole('button', { name: /Approve plan PL-0101/ })).toBeDisabled(); // reason required
  });

  it('sends plan_hash, reason and an Idempotency-Key with credentials', async () => {
    const mock = createMock();
    const { calls } = installFetch(mock);
    await openRemediation();
    const hash = mock.incidents['INC-0002'].remediation.plans[0].plan_hash;
    type('Memory pressure confirmed on EV-101');
    fireEvent.click(screen.getByRole('button', { name: /Approve plan PL-0101/ }));
    await screen.findByText(/Approved\. Decision DEC-/);
    const post = calls.find((c) => c.method === 'POST');
    expect(post?.path).toBe('/incidents/INC-0002/remediation/plans/PL-0101/approve');
    expect(post?.body).toEqual({ plan_hash: hash, reason: 'Memory pressure confirmed on EV-101' });
    expect(post?.headers['idempotency-key']).toMatch(KEY_RE);
    expect(post?.headers['content-type']).toBe('application/json');
    expect(post?.credentials).toBe('include');
    // the mock moved the incident to remediating and the panel is gone after the reload
    await waitFor(() => expect(screen.queryByLabelText('Approval for PL-0101')).toBeNull());
    // the confirmation must survive the panel disappearing (regression found by the nginx e2e run)
    expect(screen.getByTestId('notice')).toHaveTextContent(/Approved\. Decision DEC-/);
  });

  it('uses a fresh Idempotency-Key for each distinct action', async () => {
    const mock = createMock();
    const { calls } = installFetch(mock, (req) => (req.method === 'POST' ? json(409, { code: 'plan_not_pending', message: 'x' }) : undefined));
    await openRemediation();
    type('first attempt');
    fireEvent.click(screen.getByRole('button', { name: /Approve plan PL-0101/ }));
    await screen.findByRole('alert');
    fireEvent.click(screen.getByRole('button', { name: /Approve plan PL-0101/ }));
    await waitFor(() => expect(calls.filter((c) => c.method === 'POST')).toHaveLength(2));
    const [a, b] = calls.filter((c) => c.method === 'POST').map((c) => c.headers['idempotency-key']);
    expect(a).toMatch(KEY_RE);
    expect(b).toMatch(KEY_RE);
    expect(a).not.toBe(b); // a definitive 409 ends the operation; the next click is a new one
  });

  it('reuses the same key when the outcome is unknown (network failure) so a retry cannot double-apply', async () => {
    const mock = createMock();
    let first = true;
    const calls: string[] = [];
    const { fn } = installFetch(mock);
    const real = fn.getMockImplementation()!;
    fn.mockImplementation(async (input, init) => {
      if ((init?.method ?? 'GET') === 'POST') {
        calls.push(new Headers(init?.headers).get('Idempotency-Key') ?? '');
        if (first) { first = false; throw new TypeError('network down'); }
      }
      return real(input, init);
    });
    await openRemediation();
    type('retry me please');
    fireEvent.click(screen.getByRole('button', { name: /Approve plan PL-0101/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/could not be reached/);
    fireEvent.click(screen.getByRole('button', { name: /Approve plan PL-0101/ }));
    await screen.findByText(/Approved\./);
    expect(calls).toHaveLength(2);
    expect(calls[0]).toBe(calls[1]);
  });

  it('shows policy rule ids on 403 but never the raw server message', async () => {
    installFetch(createMock(), (req) => (req.method === 'POST'
      ? json(403, { code: 'policy_denied', message: '<img src=x onerror=alert(1)> Traceback (most recent call last): File "/srv/api/policy.py"', rule_ids: ['I-03', 'C-STRICT', '<script>'] })
      : undefined));
    await openRemediation();
    type('operator reason');
    fireEvent.click(screen.getByRole('button', { name: /Approve plan PL-0101/ }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/refused this action/);
    expect(alert).toHaveTextContent('policy_denied');
    expect(alert).toHaveTextContent('I-03');
    expect(alert).toHaveTextContent('C-STRICT');
    expect(alert.textContent).not.toMatch(/Traceback|policy\.py|<script>|onerror/);
    expect(alert.querySelector('img')).toBeNull();
  });

  it('rejects with a reason and its own Idempotency-Key', async () => {
    const { calls } = installFetch();
    await openRemediation();
    type('Not safe during the release window');
    fireEvent.click(screen.getByRole('button', { name: /Reject plan PL-0101/ }));
    await screen.findByText('Rejected.');
    const post = calls.find((c) => c.method === 'POST');
    expect(post?.path).toBe('/incidents/INC-0002/remediation/plans/PL-0101/reject');
    expect(post?.body).toEqual({ reason: 'Not safe during the release window' });
    expect(post?.headers['idempotency-key']).toMatch(KEY_RE);
  });

  it('the mock refuses a stale plan_hash (the UI cannot approve a different plan than shown)', () => {
    const mock = createMock();
    const bad = mock.handle({ method: 'POST', path: '/incidents/INC-0002/remediation/plans/PL-0101/approve', headers: { 'idempotency-key': 'abcdefgh1234' }, body: { plan_hash: `sha256:${'0'.repeat(64)}`, reason: 'stale' } });
    expect(bad.status).toBe(409);
  });
});
