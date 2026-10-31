import { render, screen, waitFor, within, fireEvent } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createMock } from '../mock/router.mjs';
import { installFetch, json } from './helpers';
import { nav, setupNav } from './nav-mock';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: (u: string) => nav.replace(u), push: (u: string) => nav.push(u) }),
  usePathname: () => nav.path,
  useSearchParams: () => nav.params,
}));

import { AppShell } from '@/components/AppShell';
import { AuditPage, IncidentPage, IncidentsPage, ServicePage } from '@/components/routes';
import { Overview } from '@/components/views/Overview';
import { Topology } from '@/components/views/Topology';
import { StatusBanner } from '@/components/StatusBanner';
import { Login } from '@/components/views/Login';

beforeEach(() => setupNav());

describe('Overview', () => {
  it('shows every service with state, SLIs and open incidents', async () => {
    installFetch();
    render(<Overview />);
    await screen.findByTestId('svc-api');
    expect(screen.getAllByTestId(/^svc-/)).toHaveLength(8);
    const api = screen.getByTestId('svc-api');
    expect(api).toHaveAttribute('data-state', 'DEGRADED');
    expect(within(api).getByText('error ratio')).toBeInTheDocument();
    expect(within(api).getByRole('link', { name: /INC-0002/ })).toHaveAttribute('href', expect.stringMatching(/^\/incidents\/view\/?\?id=INC-0002$/));
    expect((await screen.findAllByRole('link', { name: /INC-0003/ })).length).toBeGreaterThanOrEqual(2); // card + open-incident table
  });

  it('renders UNKNOWN and each missing-signal state distinctly, never as healthy', async () => {
    installFetch();
    render(<Overview />);
    await screen.findByTestId('svc-batch-job');
    const expected: Record<string, [string, RegExp]> = {
      'batch-job': ['no_data_expected', /No data \(expected\)/],
      notifier: ['no_data_unexpected', /No data \(UNEXPECTED\)/],
      search: ['collection_failed', /Collection FAILED/],
    };
    const classes = new Set<string>();
    for (const [name, [signal, label]] of Object.entries(expected)) {
      const card = screen.getByTestId(`svc-${name}`);
      expect(card).toHaveAttribute('data-state', 'UNKNOWN');
      const badge = card.querySelector('[data-missing-signal]');
      expect(badge).toHaveAttribute('data-missing-signal', signal);
      expect(badge).toHaveTextContent(label);
      expect(card.querySelector('.badge.st-HEALTHY')).toBeNull();
      expect(card.querySelector('.badge.st-UNKNOWN')).not.toBeNull();
      expect(within(card).getByText(/never assumed healthy/)).toBeInTheDocument();
      classes.add(badge?.className ?? '');
    }
    expect(classes.size).toBe(3);
    // a healthy service has no missing-signal badge and a different state badge
    const healthy = screen.getByTestId('svc-app-db');
    expect(healthy.querySelector('[data-missing-signal]')).toBeNull();
    expect(within(healthy).getByText(/HEALTHY/)).toBeInTheDocument();
  });
});

describe('StatusBanner', () => {
  it('shows degraded mode with the failing dependency', async () => {
    installFetch();
    render(<StatusBanner />);
    const b = await screen.findByRole('alert');
    expect(b).toHaveAttribute('data-status', 'degraded');
    expect(b).toHaveTextContent(/DEGRADED MODE/);
    expect(b).toHaveTextContent(/logs/);
  });

  it('shows a fail-closed banner', async () => {
    const mock = createMock();
    mock.setStatus('fail_closed');
    installFetch(mock);
    render(<StatusBanner />);
    const b = await screen.findByRole('alert');
    expect(b).toHaveAttribute('data-status', 'fail_closed');
    expect(b).toHaveTextContent(/FAIL CLOSED/);
    expect(b).toHaveTextContent(/actuator/);
  });

  it('treats an unreachable /status as fail closed, not as ok', async () => {
    installFetch(createMock(), () => json(503, { code: 'down', message: 'boom' }));
    render(<StatusBanner />);
    expect(await screen.findByRole('alert')).toHaveAttribute('data-status', 'unreachable');
  });

  it('shows OK quietly', async () => {
    const mock = createMock();
    mock.setStatus('ok');
    installFetch(mock);
    render(<StatusBanner />);
    expect(await screen.findByText(/System status: OK/)).toBeInTheDocument();
  });
});

describe('Topology', () => {
  it('draws one SVG node per service coloured by state, with hard and soft edges', async () => {
    installFetch();
    const { container } = render(<Topology />);
    await screen.findByTestId('node-api');
    expect(screen.getAllByTestId(/^node-/)).toHaveLength(8);
    expect(screen.getByTestId('node-redis')).toHaveAttribute('data-state', 'UNHEALTHY');
    expect(screen.getByTestId('node-search')).toHaveAttribute('data-state', 'UNKNOWN');
    expect(container.querySelectorAll('path[data-edge-kind="hard"]').length).toBeGreaterThan(0);
    expect(container.querySelectorAll('path[data-edge-kind="soft"]').length).toBe(2);
  });
});

describe('Incidents list', () => {
  it('lists incidents and filters by state through the API', async () => {
    const { calls } = installFetch();
    setupNav('/incidents/', '');
    const { rerender } = render(<IncidentsPage />);
    await screen.findByTestId('inc-INC-0001');
    expect(screen.getAllByTestId(/^inc-/)).toHaveLength(7);
    const select = screen.getByLabelText(/State/);
    fireEvent.change(select, { target: { value: 'escalated' } });
    expect(nav.replace).toHaveBeenCalledWith('/incidents/?state=escalated');
    setupNav('/incidents/', 'state=escalated');
    rerender(<IncidentsPage />);
    await waitFor(() => expect(screen.getAllByTestId(/^inc-/)).toHaveLength(1));
    expect(screen.getByTestId('inc-INC-0003')).toBeInTheDocument();
    expect(calls.some((c) => c.path === '/incidents' && c.url.includes('state=escalated'))).toBe(true);
  });
});

describe('Incident detail: every tab renders against the mock data', () => {
  const open = (tab: string, id = 'INC-0001', extra = '') => {
    setupNav('/incidents/view/', `id=${id}&tab=${tab}${extra}`);
    return render(<IncidentPage />);
  };

  it('Timeline: ordered by event_time, shows collected_at and marks suppressed events', async () => {
    const mock = createMock();
    installFetch(mock, (req) => {
      if (req.path.endsWith('/timeline')) {
        const r = mock.handle(req);
        return { status: 200, body: [...(r.body as object[])].reverse() };
      }
      return undefined;
    });
    open('timeline');
    await screen.findByTestId('tl-TL-0001');
    const rows = screen.getAllByTestId(/^tl-/);
    const times = rows.map((r) => r.querySelectorAll('td')[0]?.textContent ?? '');
    expect(times).toEqual([...times].sort());
    expect(rows).toHaveLength(7);
    const suppressed = screen.getByTestId('tl-TL-0007');
    expect(suppressed).toHaveAttribute('data-suppressed', 'true');
    expect(within(suppressed).getByText('SUPPRESSED')).toBeInTheDocument();
    // collected_at is shown, and the lag when it differs from the event time
    expect(within(screen.getByTestId('tl-TL-0001')).getByText(/\+8s/)).toBeInTheDocument();
    expect(screen.getByTestId('tl-TL-0001').querySelectorAll('td')[1]).toHaveTextContent('09:00:20Z');
  });

  it('Evidence: table with untrusted flag, escaped payload, and hostile text kept inert', async () => {
    installFetch();
    const { container } = open('evidence', 'INC-0002');
    const row = await screen.findByTestId('ev-EV-103');
    expect(within(row).getByText('UNTRUSTED')).toBeInTheDocument();
    expect(screen.getByTestId('ev-EV-101').textContent).not.toContain('UNTRUSTED');
    expect(row.textContent).toContain('<script>alert(1)</script>');
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('svg')).toBeNull();
    expect(container.querySelector('[onerror], [onload]')).toBeNull();
    expect(container.querySelector('a[href^="javascript"]')).toBeNull();
    expect(row.textContent).toContain('truncated');
    // status and missing-signal shown for non-ok evidence
    expect(within(screen.getByTestId('ev-EV-105')).getByText('empty')).toBeInTheDocument();
  });

  it('Evidence: a deep link from a claim focuses the evidence row', async () => {
    installFetch();
    open('evidence', 'INC-0002', '&ev=EV-102');
    const row = await screen.findByTestId('ev-EV-102');
    expect(row).toHaveAttribute('data-focused', 'true');
    expect(screen.getByTestId('ev-EV-101')).not.toHaveAttribute('data-focused');
  });

  it('Diagnosis: ranked hypotheses, claims, contradictions, evidence links, alternatives, unknowns', async () => {
    installFetch();
    open('diagnosis');
    const h1 = await screen.findByTestId('hyp-1');
    expect(screen.getAllByTestId(/^hyp-/).map((h) => h.getAttribute('data-testid'))).toEqual(['hyp-1', 'hyp-2']);
    expect(within(h1).getByText(/redis_unavailable/)).toBeInTheDocument();
    expect(within(h1).getByText(/ranking aid to order hypotheses; not a probability/)).toBeInTheDocument();
    expect(within(h1).getByText('Contradicting claims')).toBeInTheDocument();
    expect(within(h1).getByText('app database is healthy')).toBeInTheDocument();
    const link = within(h1).getAllByRole('link', { name: 'EV-003' })[0];
    expect(link).toHaveAttribute('href', expect.stringMatching(/^\/incidents\/view\/?\?id=INC-0001&tab=evidence&ev=EV-003$/));
    expect(within(h1).getByText('network_partition')).toBeInTheDocument();
    expect(within(h1).getByText('why redis stopped')).toBeInTheDocument();
    expect(screen.getByText(/deterministic rules/)).toBeInTheDocument();
  });

  it('Diagnosis: reports "no diagnosis yet" when the API says 404', async () => {
    installFetch();
    open('diagnosis', 'INC-0004');
    expect(await screen.findByText(/No diagnosis yet/)).toBeInTheDocument();
  });

  it('Remediation (escalated incident): attempts, circuit breaker, refusals, exact argv, L1/L2', async () => {
    installFetch();
    open('remediation', 'INC-0003');
    const budget = await screen.findByTestId('budget');
    expect(budget).toHaveTextContent(/Circuit breaker:\s*open/);
    expect(budget).toHaveTextContent(/Attempts remaining:\s*0/);
    const argv = within(screen.getByTestId('exec-EX-0201')).getByTestId('argv');
    expect([...argv.querySelectorAll('.arg')].map((e) => e.textContent)).toEqual(['docker', 'restart', 'cd-worker']);
    const refused = screen.getByTestId('exec-EX-0203');
    expect(refused).toHaveTextContent(/refused/);
    expect(refused).toHaveTextContent(/Refused by: I-04/);
    expect(refused).toHaveTextContent(/no command executed/);
    const denied = screen.getByTestId('dec-DEC-0203');
    expect(denied).toHaveTextContent(/Layer 1.*deny.*I-04/);
    expect(denied).toHaveTextContent(/Layer 2.*deny/);
    expect(screen.queryByLabelText(/Approval for/)).toBeNull();
  });

  it('Verification: pre/post/baseline, failed checks, and unverifiable shown clearly', async () => {
    installFetch();
    open('verification', 'INC-0005');
    const v = await screen.findByTestId('ver-EX-0501');
    expect(within(v).getByText('UNVERIFIABLE')).toBeInTheDocument();
    expect(v).toHaveTextContent(/does not claim recovery \(fail closed\)/);
    expect(within(screen.getByTestId('chk-telemetry_fresh')).getByText(/UNKNOWN/)).toBeInTheDocument();
    expect(within(screen.getByTestId('chk-error_sli')).getByText(/PASS/)).toBeInTheDocument();
    const cells = screen.getByTestId('chk-error_sli').querySelectorAll('td');
    expect([cells[2]?.textContent, cells[3]?.textContent, cells[4]?.textContent]).toEqual(['0.002', '0.2', '0.003']);
  });

  it('Verification: failing and recovered verdicts', async () => {
    installFetch();
    open('verification', 'INC-0003');
    const v = await screen.findByTestId('ver-EX-0201');
    expect(within(v).getByText('RELAPSE')).toBeInTheDocument();
    expect(within(screen.getByTestId('ver-EX-0202')).getByText('FAILED')).toBeInTheDocument();
    expect(within(v).getAllByText(/FAIL/).length).toBeGreaterThan(0);
  });

  it('Report: outcome keeps mitigation and root-cause confirmation separate; markdown is offered', async () => {
    const { calls } = installFetch();
    open('report');
    const outcome = await screen.findByTestId('outcome');
    expect(outcome).toHaveTextContent(/Mitigated \(service restored\): true/);
    expect(outcome).toHaveTextContent(/Root cause confirmed: false/);
    expect(screen.getByText('Limitations')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Show Markdown' }));
    const md = await screen.findByTestId('markdown');
    expect(md).toHaveTextContent('# Incident report INC-0001');
    expect(calls.some((c) => c.path.endsWith('/report') && c.headers.accept === 'text/markdown')).toBe(true);
    expect(screen.getByRole('button', { name: 'Download Markdown' })).toBeInTheDocument();
  });

  it('Report: an incident without diagnosis has no report yet', async () => {
    installFetch();
    open('report', 'INC-0004');
    expect(await screen.findByText(/No report is available yet/)).toBeInTheDocument();
  });

  it('switching tabs updates the URL', async () => {
    installFetch();
    open('timeline');
    await screen.findByTestId('tl-TL-0001');
    fireEvent.click(screen.getByRole('tab', { name: 'RCA' }));
    expect(nav.replace).toHaveBeenCalledWith('/incidents/view/?id=INC-0001&tab=diagnosis');
  });

  it('rejects an invalid incident id from the URL without calling the API', () => {
    const { fn } = installFetch();
    setupNav('/incidents/view/', 'id=../../etc/passwd&tab=timeline');
    render(<IncidentPage />);
    expect(screen.getByRole('alert')).toHaveTextContent(/invalid incident id/);
    expect(fn).not.toHaveBeenCalled();
  });
});

describe('Service detail: metrics sparklines and logs', () => {
  it('renders SVG sparklines and escaped logs for api', async () => {
    installFetch();
    setupNav('/services/view/', 'name=api');
    const { container } = render(<ServicePage />);
    await screen.findByTestId('spark-error_ratio');
    expect(container.querySelectorAll('figure.spark svg polyline')).toHaveLength(5);
    const logs = await screen.findByTestId('loglines');
    expect(logs.textContent).toContain('<script>alert(1)</script>');
    expect(logs.querySelector('script, img, svg')).toBeNull();
    expect(logs.textContent).toContain('truncated');
  });

  it('shows "no data" (not zero) for an UNKNOWN service', async () => {
    installFetch();
    setupNav('/services/view/', 'name=search');
    render(<ServicePage />);
    await waitFor(() => expect(screen.getAllByText(/no data \(timeout\)/).length).toBe(5));
    expect(await screen.findByText(/Absence of logs is not evidence of health/)).toBeInTheDocument();
    expect(screen.getByText(/Collection FAILED/)).toBeInTheDocument();
  });
});

describe('Audit view', () => {
  it('shows a valid chain badge', async () => {
    installFetch();
    setupNav('/audit/', '');
    render(<AuditPage />);
    const s = await screen.findByTestId('chain-status');
    expect(s).toHaveTextContent('CHAIN VALID');
    expect(screen.getAllByRole('row').length).toBeGreaterThan(5);
  });

  it('shows a broken chain prominently', async () => {
    installFetch();
    setupNav('/audit/', 'incident=INC-0003');
    render(<AuditPage />);
    const s = await screen.findByTestId('chain-status');
    expect(s).toHaveTextContent('CHAIN BROKEN');
    expect(screen.getByRole('alert')).toHaveTextContent(/did not verify/);
  });
});

describe('Login and shell', () => {
  it('logs in with a token and goes to the overview', async () => {
    const { calls } = installFetch();
    render(<Login />);
    const submit = screen.getByRole('button', { name: 'Sign in' });
    expect(submit).toBeDisabled();
    fireEvent.change(document.querySelector('input[type=password]') as HTMLInputElement, { target: { value: 'a-long-token' } });
    fireEvent.click(submit);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith('/'));
    expect(calls[0]).toMatchObject({ method: 'POST', path: '/auth/login', body: { token: 'a-long-token' }, credentials: 'include' });
  });

  it('shows a safe message when login fails', async () => {
    installFetch(createMock(), () => json(401, { code: 'invalid_token', message: '<b>stack trace at db.py:42</b>' }));
    render(<Login />);
    fireEvent.change(document.querySelector('input[type=password]') as HTMLInputElement, { target: { value: 'wrong-token' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/session is missing or expired/);
    expect(alert.textContent).not.toContain('stack trace');
  });

  it('shell shows nav, a connection indicator and no chrome on /login', async () => {
    installFetch();
    setupNav('/', '');
    const { unmount } = render(<AppShell><p>child</p></AppShell>);
    expect(screen.getByRole('navigation', { name: 'Main' })).toBeInTheDocument();
    expect(document.querySelector('[data-conn]')).toBeTruthy();
    unmount();
    setupNav('/login/', '');
    render(<AppShell><p>child</p></AppShell>);
    expect(screen.queryByRole('navigation', { name: 'Main' })).toBeNull();
  });
});
