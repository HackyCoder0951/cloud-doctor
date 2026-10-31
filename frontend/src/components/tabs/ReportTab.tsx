'use client';
import { useState } from 'react';
import { api, ApiError, describeError } from '@/api/client';
import type { Report } from '@/api/types';
import { ErrorNote, fmtTime } from '@/components/common';
import { Tag, VerdictBadge } from '@/components/badges';
import { EpistemicBadge, NotAvailable, Panel, Skeleton } from '@/components/ui';
import { problemOf, topHypothesis } from '@/lib/incident-view';
import { jsonText, Untrusted } from '@/lib/untrusted';
import { useApi } from '@/lib/useApi';

function Postmortem({ r }: { r: NonNullable<ReturnType<typeof useApi<Report>>['data']> }) {
  const top = topHypothesis(r.diagnosis);
  const lastVer = r.verifications[r.verifications.length - 1];
  return (
    <div className="stack" data-testid="postmortem">
      <h2>Postmortem</h2>
      <div className="split">
        <Panel title="Impact">
          <p><Untrusted value={problemOf(r.incident, r.diagnosis).text} max={300} /></p>
          <p className="muted">Severity {r.incident.severity} · services <Untrusted value={r.incident.services.join(', ')} max={200} /> · opened {fmtTime(r.incident.opened_at)}</p>
        </Panel>
        <Panel title="Root cause" aside={<EpistemicBadge kind={r.outcome.root_cause_confirmed ? 'CONFIRMED' : top ? 'HYPOTHESIS' : 'UNKNOWN'} />}>
          {top ? <p><code><Untrusted value={top.cause_id} max={80} /></code> <span className="muted">ranking {top.confidence.toFixed(2)}, not a probability</span></p> : <p className="muted">No diagnosis, so no root cause is stated.</p>}
          {!r.outcome.root_cause_confirmed && top ? <p className="muted">Not confirmed. Mitigation and root cause are separate: service restoration does not prove this cause.</p> : null}
        </Panel>
      </div>
      <div className="split">
        <Panel title="Trigger"><NotAvailable what="Trigger" why="No deployment or code-change feed is connected, so what triggered the fault is not known." /></Panel>
        <Panel title="Resolution">
          {r.executions.length === 0 ? <p className="muted">No action was executed.</p> : <ul className="claims">{r.executions.map((x) => <li key={x.execution_id}><code>{x.execution_id}</code> <Tag kind={`ex-${x.result}`}>{x.result}</Tag> <Untrusted value={x.executed_argv?.length ? x.executed_argv.join(' ') : 'no command executed'} max={160} /></li>)}</ul>}
        </Panel>
      </div>
      <div className="split">
        <Panel title="Verification">{lastVer ? <p><VerdictBadge verdict={lastVer.verdict} /> <span className="muted">over {fmtTime(lastVer.window_start)} to {fmtTime(lastVer.window_end)}</span></p> : <p className="muted">Not verified. The incident is not considered recovered without a verification.</p>}</Panel>
        <Panel title="Follow-up actions"><NotAvailable what="Follow-up actions" why="Cloud Doctor does not generate follow-up tasks. Record them in your own tracker after review." /></Panel>
      </div>
    </div>
  );
}

export function ReportTab({ incident }: { incident: string }) {
  const { data, error, loading } = useApi(() => api.getReport(incident), [incident]);
  const [md, setMd] = useState<string | null>(null);
  const [mdError, setMdError] = useState<string | null>(null);

  const loadMarkdown = async () => {
    setMdError(null);
    try { setMd(await api.getReportMarkdown(incident)); } catch (e) { setMdError(describeError(e)); }
  };
  const download = async () => {
    setMdError(null);
    try {
      const text = md ?? (await api.getReportMarkdown(incident));
      setMd(text);
      const url = URL.createObjectURL(new Blob([text], { type: 'text/markdown' }));
      const a = document.createElement('a');
      a.href = url;
      a.download = `${incident}-report.md`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { setMdError(describeError(e)); }
  };

  const notReady = error instanceof ApiError && error.kind === 'not_found';
  const raw = data ? jsonText(data, 20000) : null;
  return (
    <section aria-label="Report">
      {notReady ? <p className="muted">No report is available yet (the incident has no diagnosis).</p> : <ErrorNote error={error} what="Report" />}
      {loading && !data ? <Skeleton label="report" lines={5} /> : null}
      {data ? (
        <>
          <p className="muted">Generated {fmtTime(data.generated_at)} · mode <Tag kind="origin">{data.generator.mode}</Tag> · <Untrusted value={data.generator.version} max={30} /></p>
          <Postmortem r={data} />
          <h3>Outcome</h3>
          <ul className="outcome" data-testid="outcome">
            <li>Mitigated (service restored): <strong>{String(data.outcome.mitigated)}</strong></li>
            <li>Root cause confirmed: <strong>{String(data.outcome.root_cause_confirmed)}</strong> <span className="muted">(separate from mitigation)</span></li>
            <li>Escalated: <strong>{String(data.outcome.escalated)}</strong></li>
          </ul>
          <h3>Top hypothesis</h3>
          {data.diagnosis.hypotheses[0] ? <p><Untrusted value={data.diagnosis.hypotheses[0].cause_id} max={60} /> — <Untrusted value={data.diagnosis.hypotheses[0].description} max={300} /> <span className="muted">(ranking score {data.diagnosis.hypotheses[0].confidence.toFixed(2)}, not a probability)</span></p> : null}
          <h3>Actions and verification</h3>
          <p>{data.plans.length} plans · {data.decisions.length} decisions · {data.executions.length} executions · {data.timeline.length} timeline events · {data.evidence_ids.length} evidence records</p>
          <p className="row">{data.verifications.map((v) => <span key={v.execution_id}>{v.execution_id}: <VerdictBadge verdict={v.verdict} /></span>)}</p>
          <h3>Limitations</h3>
          <ul>{data.limitations.map((l, i) => <li key={i}><Untrusted value={l} max={300} /></li>)}</ul>
          <h3>Markdown report</h3>
          <p className="row">
            <button type="button" onClick={loadMarkdown}>Show Markdown</button>
            <button type="button" onClick={download}>Download Markdown</button>
          </p>
          {mdError ? <p role="alert" className="error">{mdError}</p> : null}
          {md !== null ? <pre className="payload" data-testid="markdown"><Untrusted value={md} max={20000} /></pre> : null}
          <details>
            <summary>Raw report JSON</summary>
            <pre className="payload"><Untrusted value={raw?.text ?? ''} max={20000} /></pre>
          </details>
        </>
      ) : null}
    </section>
  );
}
