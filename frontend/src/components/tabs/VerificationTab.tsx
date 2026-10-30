'use client';
import { api } from '@/api/client';
import type { Verification } from '@/api/types';
import { ErrorNote, fmtNum, fmtTime, Loading } from '@/components/common';
import { EvidenceLinks } from '@/components/EvidenceLink';
import { useLiveReload } from '@/components/Live';
import { VerdictBadge } from '@/components/badges';
import { Untrusted } from '@/lib/untrusted';
import { useApi } from '@/lib/useApi';

export function CheckResult({ passed }: { passed: boolean | null }) {
  if (passed === true) return <span className="badge chk-pass" data-check="pass">✔ PASS</span>;
  if (passed === false) return <span className="badge chk-fail" data-check="fail">✖ FAIL</span>;
  return <span className="badge chk-unknown" data-check="unknown">? UNKNOWN</span>;
}

function VerificationView({ incident, v }: { incident: string; v: Verification }) {
  return (
    <article className={`card ver vd-${v.verdict}`} data-testid={`ver-${v.execution_id}`}>
      <header>
        <h3>Execution {v.execution_id}</h3> <VerdictBadge verdict={v.verdict} />
        <span className="muted">stability window {fmtTime(v.window_start)} → {fmtTime(v.window_end)}</span>
      </header>
      {v.verdict === 'unverifiable' ? (
        <p role="note" className="banner banner-degraded"><strong>Unverifiable.</strong> At least one check could not be established, so Cloud Doctor does not claim recovery (fail closed). This is not a pass.</p>
      ) : null}
      {v.verdict === 'recovered' ? <p className="muted">Recovered requires every check to pass over the stability window.</p> : null}
      <table className="table">
        <thead><tr><th>Check</th><th>Result</th><th>Baseline</th><th>Pre-action</th><th>Post-action</th><th>Detail</th><th>Evidence</th></tr></thead>
        <tbody>
          {v.checks.map((c) => (
            <tr key={c.name} data-testid={`chk-${c.name}`}>
              <td>{c.name}</td>
              <td><CheckResult passed={c.passed} /></td>
              <td>{fmtNum(c.baseline, 4)}</td>
              <td>{fmtNum(c.pre_action, 4)}</td>
              <td>{fmtNum(c.post_action, 4)}</td>
              <td>{c.detail ? <Untrusted value={c.detail} max={300} /> : '—'}</td>
              <td><EvidenceLinks incident={incident} ids={c.evidence} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </article>
  );
}

export function VerificationTab({ incident }: { incident: string }) {
  const { data, error, loading, reload } = useApi(() => api.getVerification(incident), [incident]);
  useLiveReload(reload, (e) => e.incident_id === incident && (e.type === 'verification.finished' || e.type === 'execution.finished'));
  return (
    <section aria-label="Verification">
      <ErrorNote error={error} what="Verification" />
      {loading && !data ? <Loading what="verification" /> : null}
      {data && data.length === 0 ? <p className="muted">No verification has run yet. Without a verification the incident is not considered recovered.</p> : null}
      {(data ?? []).map((v) => <VerificationView key={v.execution_id} incident={incident} v={v} />)}
    </section>
  );
}
