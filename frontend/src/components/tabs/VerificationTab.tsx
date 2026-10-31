'use client';
import { api } from '@/api/client';
import type { Verification } from '@/api/types';
import { ErrorNote, fmtNum, fmtTime } from '@/components/common';
import { EvidenceLinks } from '@/components/EvidenceLink';
import { useLiveReload } from '@/components/Live';
import { VerdictBadge } from '@/components/badges';
import { Skeleton } from '@/components/ui';
import { Untrusted } from '@/lib/untrusted';
import { useApi } from '@/lib/useApi';

export function CheckResult({ passed }: { passed: boolean | null }) {
  if (passed === true) return <span className="badge chk-pass" data-check="pass">✔ PASS</span>;
  if (passed === false) return <span className="badge chk-fail" data-check="fail">✖ FAIL</span>;
  return <span className="badge chk-unknown" data-check="unknown">? UNKNOWN</span>;
}

/** Before / after for the checks that report both numbers. A bar is only drawn when both values exist; otherwise the gap is stated. */
export function MetricComparison({ checks }: { checks: Verification['checks'] }) {
  const rows = checks.filter((c) => c.pre_action !== undefined || c.post_action !== undefined);
  if (rows.length === 0) return <p className="muted">No check reported before/after values.</p>;
  return (
    <div className="compare" data-testid="metric-comparison">
      {rows.map((c) => {
        const top = Math.max(c.pre_action ?? 0, c.post_action ?? 0, c.baseline ?? 0) || 1;
        return (
          <div key={c.name} className="compare__row">
            <span className="compare__name mono">{c.name}</span>
            <span className="compare__cell">Before {c.pre_action !== undefined ? <><meter min={0} max={top} value={c.pre_action} aria-label={`${c.name} before`} /> <span className="mono">{fmtNum(c.pre_action, 4)}</span></> : <span className="muted">not reported</span>}</span>
            <span className="compare__cell">After {c.post_action !== undefined ? <><meter min={0} max={top} value={c.post_action} aria-label={`${c.name} after`} /> <span className="mono">{fmtNum(c.post_action, 4)}</span></> : <span className="muted">not reported</span>}</span>
            <span className="compare__cell muted">Baseline {c.baseline !== undefined ? <span className="mono">{fmtNum(c.baseline, 4)}</span> : 'not reported'}</span>
          </div>
        );
      })}
    </div>
  );
}

function windowSeconds(v: Verification): number | null {
  const a = Date.parse(v.window_start); const b = Date.parse(v.window_end);
  return Number.isFinite(a) && Number.isFinite(b) && b >= a ? Math.round((b - a) / 1000) : null;
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
      <p className="muted">Stability window: <strong className="mono">{windowSeconds(v) === null ? 'not reported' : `${windowSeconds(v)} s`}</strong> · {v.checks.filter((c) => c.passed === true).length} passed, {v.checks.filter((c) => c.passed === false).length} failed, {v.checks.filter((c) => c.passed === null).length} unknown of {v.checks.length} checks</p>
      <ul className="checklist" aria-label="Checks">
        {v.checks.map((c) => <li key={c.name} data-check={c.passed === true ? 'pass' : c.passed === false ? 'fail' : 'unknown'}><span aria-hidden="true">{c.passed === true ? '✓' : c.passed === false ? '✕' : '?'}</span> <span className="mono">{c.name}</span> <CheckResult passed={c.passed} /></li>)}
      </ul>
      <h4>Before / after</h4>
      <MetricComparison checks={v.checks} />
      <h4>Check detail</h4>
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
      {loading && !data ? <Skeleton label="verification" lines={4} /> : null}
      {data && data.length === 0 ? <p className="muted">No verification has run yet. Without a verification the incident is not considered recovered.</p> : null}
      {(data ?? []).map((v) => <VerificationView key={v.execution_id} incident={incident} v={v} />)}
    </section>
  );
}
