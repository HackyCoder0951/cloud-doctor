import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { installFetch } from './helpers';
import { nav, setupNav } from './nav-mock';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: (u: string) => nav.replace(u), push: (u: string) => nav.push(u) }),
  usePathname: () => nav.path,
  useSearchParams: () => nav.params,
}));

import { AppShell } from '../src/components/AppShell';
import { IncidentPage, IncidentsPage } from '../src/components/routes';
import { AccessView } from '../src/components/views/AccessView';
import { AutomationView } from '../src/components/views/AutomationView';
import { Overview } from '../src/components/views/Overview';

beforeEach(() => { cleanup(); setupNav(); window.localStorage.clear(); delete document.documentElement.dataset.theme; });
afterEach(() => { vi.unstubAllGlobals(); });

const open = (id: string, tab: string) => { setupNav('/incidents/view/', `id=${id}&tab=${tab}`); return render(<IncidentPage />); };

describe('global header', () => {
  it('always shows the environment, the live state and the open incident count, with Automation and Access in the nav', async () => {
    installFetch();
    render(<AppShell><p>x</p></AppShell>);
    expect(screen.getByTestId('environment')).toHaveTextContent('SANDBOX');
    expect(document.querySelector('[data-conn]')).toBeTruthy();
    const nav = screen.getByRole('navigation', { name: 'Main' });
    for (const n of ['Overview', 'Topology', 'Incidents', 'Automation', 'Audit', 'Access']) expect(within(nav).getByRole('link', { name: n })).toBeInTheDocument();
    expect(await screen.findByTestId('open-count')).toHaveTextContent(/5 open incidents/);
  });

  it('switches theme, remembers it, and still works when storage is blocked', async () => {
    installFetch();
    render(<AppShell><p>x</p></AppShell>);
    expect(document.documentElement.dataset.theme).toBe('dark');
    fireEvent.click(screen.getByRole('button', { name: /Switch to light theme/ }));
    expect(document.documentElement.dataset.theme).toBe('light');
    expect(window.localStorage.getItem('cd-theme')).toBe('light');
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
    fireEvent.click(screen.getByRole('button', { name: /Switch to dark theme/ }));
    expect(document.documentElement.dataset.theme).toBe('dark');
    spy.mockRestore();
  });
});

describe('incident workspace: summary', () => {
  it('opens on a header that says what happened, how bad, and that a human is needed', async () => {
    installFetch();
    open('INC-0002', 'summary');
    expect(await screen.findByTestId('phase')).toHaveTextContent('NEEDS HUMAN');
    expect(screen.getByTestId('severity')).toHaveTextContent('HIGH');
    expect(screen.getByRole('heading', { level: 1 })).not.toHaveTextContent(/^INC-/);
    expect(screen.getByText(/Title taken from the first reported symptom/)).toBeInTheDocument();
    const steps = within(screen.getByTestId('lifecycle')).getAllByRole('button');
    expect(steps.map((s) => s.textContent?.replace(/\s+/g, ' ').trim())).toEqual(['✓Detected (done)', '✓Diagnosed (done)', '●Acting (in progress)', '○Verified (not started)']);
  });

  it('explains a lifecycle stage when it is clicked', async () => {
    installFetch();
    open('INC-0002', 'summary');
    await screen.findByTestId('lifecycle');
    fireEvent.click(await screen.findByRole('button', { name: /Verified/ }));
    expect(screen.getByText(/Without one the incident is not considered recovered/)).toBeInTheDocument();
  });

  it('shows the likely cause with a ranking that is explicitly not a probability, and "not reported" instead of a made-up coverage', async () => {
    installFetch();
    open('INC-0002', 'summary');
    const m = await screen.findByTestId('cause-metrics');
    expect(m).toHaveTextContent(/Hypothesis ranking/);
    expect(m).toHaveTextContent(/Evidence coverage\s*not reported/);
    expect(m).toHaveTextContent(/Independent signal types\s*not reported/);
    expect(screen.getByText(/not a probability that the cause is true/)).toBeInTheDocument();
    expect(document.querySelector('.cause')).toHaveTextContent('redis_memory_exhausted');
  });

  it('lists what Cloud Doctor knows (observations only) and does not know', async () => {
    installFetch();
    open('INC-0002', 'summary');
    const knows = await screen.findByRole('region', { name: 'What Cloud Doctor knows' });
    expect(within(knows).getAllByTestId('epi-OBSERVED').length).toBeGreaterThan(0);
    expect(within(knows).queryByTestId('epi-INFERRED')).toBeNull();
    const unknown = screen.getByRole('region', { name: 'What Cloud Doctor does not know' });
    expect(within(unknown).getByText('why memory grew')).toBeInTheDocument();
  });

  it('with no diagnosis it says so and states no conclusion', async () => {
    installFetch();
    open('INC-0004', 'summary');
    expect(await screen.findByText('No diagnosis yet')).toBeInTheDocument();
    expect(screen.getByText(/Nothing here is a conclusion/)).toBeInTheDocument();
  });

  it('the action rail offers the approval review and jumps to Remediation', async () => {
    installFetch();
    open('INC-0002', 'summary');
    const rail = await screen.findByTestId('action-rail');
    await within(rail).findByText(/Approval required/);
    fireEvent.click(within(rail).getByRole('button', { name: /Review plan PL-0101/ }));
    expect(nav.replace).toHaveBeenCalledWith('/incidents/view/?id=INC-0002&tab=remediation');
  });

  it('an escalated incident is blocked and says automation stopped', async () => {
    installFetch();
    open('INC-0003', 'summary');
    const rail = await screen.findByTestId('action-rail');
    await within(rail).findByText(/Automation is stopped/);
    expect(within(screen.getByTestId('lifecycle')).getByRole('button', { name: /Acting \(blocked\)/ })).toBeInTheDocument();
  });

  it('opens the evidence drawer from a summary evidence link', async () => {
    installFetch();
    open('INC-0002', 'summary');
    const knows = await screen.findByRole('region', { name: 'What Cloud Doctor knows' });
    fireEvent.click(within(knows).getAllByRole('link', { name: /^EV-/ })[0] as HTMLElement);
    expect(await screen.findByTestId('evidence-drawer')).toBeInTheDocument();
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByTestId('evidence-drawer')).toBeNull());
  });
});

describe('remediation, verification and evidence presentation', () => {
  it('shows the policy check, the execution timeline and no patch panel when the plan has no patch', async () => {
    installFetch();
    open('INC-0001', 'remediation');
    const checks = await screen.findByTestId('policy-checks');
    expect(checks).toHaveTextContent(/Layer 1 invariants passed/);
    expect(checks).toHaveTextContent(/Sandbox required/);
    expect(screen.getByTestId('exec-timeline')).toHaveTextContent(/Execution EX-0001 success/);
    expect(screen.queryByText('Proposed patch')).toBeNull();
  });

  it('makes a denial loud: BLOCKED with the reason', async () => {
    installFetch();
    open('INC-0003', 'remediation');
    const blocked = (await screen.findAllByRole('alert')).find((a) => /BLOCKED/.test(a.textContent ?? ''));
    expect(blocked).toHaveTextContent(/attempt budget exhausted/);
  });

  it('the approval panel summarises action, risk, environment and what the API does not report', async () => {
    installFetch();
    open('INC-0002', 'remediation');
    const s = await screen.findByTestId('approval-summary');
    expect(s).toHaveTextContent(/restart_service/);
    expect(s).toHaveTextContent('SANDBOX');
    expect(s).toHaveTextContent(/Rollback\s*not reported by the API/);
  });

  it('verification shows before/after values, the window length, and a count of unknown checks', async () => {
    installFetch();
    open('INC-0005', 'verification');
    const cmp = await screen.findByTestId('metric-comparison');
    expect(cmp.textContent).toMatch(/Before/);
    expect(cmp.textContent).toMatch(/After/);
    expect(screen.getByText(/Stability window:/)).toHaveTextContent(/\d+ s/);
    expect(screen.getByText(/unknown of/)).toBeInTheDocument();
  });

  it('evidence cards carry a role and a trust label, and can be filtered', async () => {
    installFetch();
    open('INC-0002', 'evidence');
    const cards = await screen.findByTestId('evidence-cards');
    await waitFor(() => expect(within(cards).getAllByText('SUPPORTING').length).toBeGreaterThan(0));
    expect(within(cards).getAllByText(/SYSTEM TELEMETRY|UNTRUSTED TEXT/).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole('button', { name: 'Contradicting' }));
    await waitFor(() => expect(within(screen.getByTestId('evidence-cards')).queryAllByText('SUPPORTING')).toHaveLength(0));
  });

  it('the report has a postmortem whose trigger and follow-up are stated as not available', async () => {
    installFetch();
    open('INC-0001', 'report');
    const pm = await screen.findByTestId('postmortem');
    expect(within(pm).getAllByTestId('not-available').map((n) => n.textContent).join(' ')).toMatch(/Trigger: not available[\s\S]*Follow-up actions: not available/);
  });
});

describe('overview and queue', () => {
  it('counts and ranks: incidents that need a human lead (escalated critical before approval-pending high), and pending approvals are counted', async () => {
    installFetch();
    render(<Overview />);
    const attn = await screen.findByTestId('needs-attention');
    await waitFor(() => expect(screen.getByTestId('tile-pending-approvals')).toHaveTextContent(/^1/));
    expect(screen.getByTestId('tile-open-incidents')).toHaveTextContent(/^5/);
    await waitFor(() => expect(within(attn).getAllByTestId(/^attn-/).map((c) => c.getAttribute('data-testid')).slice(0, 2)).toEqual(['attn-INC-0003', 'attn-INC-0002']));
    const second = within(attn).getByTestId('attn-INC-0002');
    expect(within(second).getByText('NEEDS HUMAN')).toBeInTheDocument();
    expect(within(second).getByRole('link', { name: /View investigation/ })).toHaveAttribute('href', expect.stringMatching(/^\/incidents\/view\/?\?id=INC-0002$/));
  });

  it('shows recent recovery actions with their result', async () => {
    installFetch();
    render(<Overview />);
    const list = await screen.findByTestId('recent-actions');
    expect(list).toHaveTextContent(/restart_service/);
  });

  it('the queue filters by "Needs human" and "Closed"', async () => {
    installFetch();
    setupNav('/incidents/', '');
    render(<IncidentsPage />);
    await screen.findByTestId('inc-INC-0001');
    fireEvent.click(screen.getByRole('button', { name: 'Needs human' }));
    await waitFor(() => expect(screen.getAllByTestId(/^inc-/).map((r) => r.getAttribute('data-testid'))).toEqual(expect.arrayContaining(['inc-INC-0002'])));
    expect(screen.queryByTestId('inc-INC-0001')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Closed' }));
    await waitFor(() => expect(screen.getAllByTestId(/^inc-/).map((r) => r.getAttribute('data-testid'))).toEqual(['inc-INC-0001', 'inc-INC-0006'].sort()));
  });
});

describe('automation and access', () => {
  it('automation reports the dependencies from /status and does not invent an auto-execution switch', async () => {
    installFetch();
    render(<AutomationView />);
    expect(await screen.findByTestId('overall')).toHaveTextContent(/DEGRADED/);
    expect(screen.getByText('Actuator')).toBeInTheDocument();
    expect(screen.getByText(/does not report an auto-execution switch/)).toBeInTheDocument();
    expect(screen.getByText('OFF')).toBeInTheDocument();
  });

  it('access states that users and roles are not available instead of showing a role table', async () => {
    installFetch();
    render(<AccessView />);
    expect(screen.getByTestId('not-available')).toHaveTextContent(/Current user and roles: not available/);
  });
});
