'use client';
import { useState } from 'react';
import { api, ApiError, describeError } from '@/api/client';
import { ErrorNote, fmtTime, Loading } from '@/components/common';
import { Tag, VerdictBadge } from '@/components/badges';
import { jsonText, Untrusted } from '@/lib/untrusted';
import { useApi } from '@/lib/useApi';

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
      {loading && !data ? <Loading what="report" /> : null}
      {data ? (
        <>
          <p className="muted">Generated {fmtTime(data.generated_at)} · mode <Tag kind="origin">{data.generator.mode}</Tag> · <Untrusted value={data.generator.version} max={30} /></p>
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
