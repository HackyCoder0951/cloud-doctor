'use client';
import { api } from '@/api/client';
import { Panel, NotAvailable, Pill } from '@/components/ui';
import { useApi } from '@/lib/useApi';

/** The API has no user, role or permission endpoint (contract change request frontend-3 is deferred), so this page explains
 *  where authorization lives instead of showing a role table it cannot know. */
export function AccessView() {
  const status = useApi(() => api.getStatus(), []);
  const l2 = status.data?.dependencies.find((d) => d.name === 'policy_layer2');
  return (
    <>
      <h1>Access</h1>
      <p className="muted">Who may do what is decided by the API, not by this interface. Hiding a button here never grants or removes a permission.</p>
      <NotAvailable what="Current user and roles" why={<>The API has no <code>/auth/me</code> or role endpoint yet (contract change request frontend-3). Sessions use one shared token, so there is no per-user identity to display and an approval is recorded under a generic operator.</>} />
      <div className="split">
        <Panel title="Policy layers">
          <ul className="claims">
            <li><strong>Layer 1, invariants.</strong> Mandatory and fail closed: catalogue action, sandbox target, risk ceiling, attempt budget, evidence precondition, parameter patterns, dependency awareness.</li>
            <li><strong>Layer 2, client policy.</strong> Can only tighten. {l2 ? <Pill tone={l2.state === 'up' ? 'ok' : 'unknown'} glyph={l2.state === 'up' ? '✓' : '–'}>{l2.state === 'up' ? 'ACTIVE' : l2.state.toUpperCase()}</Pill> : <span className="muted">status not loaded</span>}</li>
          </ul>
        </Panel>
        <Panel title="Safety rules">
          <ul className="claims">
            <li>Never an arbitrary command: only fixed argv from the action catalogue.</li>
            <li>Never a non-sandbox target.</li>
            <li>Never a high-risk action; databases are escalated, not restarted.</li>
            <li>Approval is bound to a plan hash and recorded in the audit chain.</li>
          </ul>
        </Panel>
      </div>
    </>
  );
}
