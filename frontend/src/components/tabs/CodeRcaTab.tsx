'use client';
import { useState } from 'react';
import { describeError } from '@/api/client';
import { CodeViewer, GitContext, rankingBand, StackTraceViewer } from '@/components/code/CodeViews';
import { EvidenceLinks } from '@/components/EvidenceLink';
import { EmptyState, EpistemicBadge, Meter, NotAvailable, Panel, Pill, Skeleton } from '@/components/ui';
import { RANKING_NOTE, type CodeFinding } from '@/lib/code-analysis';
import { Untrusted } from '@/lib/untrusted';
import type { IncidentBundle } from '@/lib/useIncidentBundle';

function Finding({ incident, f }: { incident: string; f: CodeFinding }) {
  const [sel, setSel] = useState<{ loc: number; line?: number }>({ loc: 0 });
  const loc = f.locations[sel.loc];
  return (
    <article className="finding" data-testid={`code-finding-${f.code_rca_id}`}>
      <header className="finding__head">
        <div className="row">
          <EpistemicBadge kind={f.status === 'confirmed' ? 'CONFIRMED' : 'HYPOTHESIS'} />
          <Pill tone={f.status === 'rejected' ? 'bad' : f.status === 'strong_candidate' || f.status === 'confirmed' ? 'ok' : 'warn'} glyph="●">{f.status.replace('_', ' ').toUpperCase()}</Pill>
          <span className="muted">service <Untrusted value={f.service} max={40} /></span>
          <span className="spacer" />
          <span className="muted mono">{f.code_rca_id}</span>
        </div>
        <h2 className="finding__title"><Untrusted value={f.title} max={200} /></h2>
        <p className="row" data-testid="code-ranking">
          <span>Ranking <Meter value={f.ranking} label="code finding ranking" /></span>
          <span>Ranking band <strong>{rankingBand(f)}</strong></span>
          <span className="muted">{f.evidence_ids.length} evidence item{f.evidence_ids.length === 1 ? '' : 's'}</span>
        </p>
        <p className="faint">{RANKING_NOTE}</p>
      </header>

      {loc ? (
        <div className="split split--code">
          <div>
            <CodeViewer loc={loc} focusLine={sel.line} />
            {f.locations.length > 1 ? (
              <p className="row" role="group" aria-label="Other locations">
                {f.locations.map((l, k) => <button key={k} type="button" className={k === sel.loc ? '' : 'ghost'} onClick={() => setSel({ loc: k })}><span className="mono">{l.file.split('/').pop()}:{l.line_start}</span></button>)}
              </p>
            ) : null}
          </div>
          <Panel title="Why this line?">
            <dl className="facts">
              <dt>Runtime evidence</dt><dd>{f.evidence_ids.length ? <EvidenceLinks incident={incident} ids={f.evidence_ids} /> : <span className="muted">none cited</span>}</dd>
              <dt>Observed</dt><dd>{f.runtime_symptoms.length ? <ul className="claims">{f.runtime_symptoms.map((s, k) => <li key={k}><Untrusted value={s} max={200} /></li>)}</ul> : <span className="muted">no runtime symptoms listed</span>}</dd>
              <dt>Code relationship</dt><dd className="mono"><Untrusted value={loc.symbol ?? 'symbol not reported'} max={120} /></dd>
              <dt>Repository</dt><dd className="mono"><Untrusted value={loc.repository} max={80} />{loc.branch ? <> @ <Untrusted value={loc.branch} max={60} /></> : null}{loc.commit ? <> · <Untrusted value={loc.commit.slice(0, 12)} max={12} /></> : null}</dd>
              <dt>Related incident</dt><dd className="mono">{incident}</dd>
            </dl>
          </Panel>
        </div>
      ) : <NotAvailable what="Source location" why="The analysis names this finding but did not collect any file, line or snippet for it." />}

      {f.stack_trace.length > 0 ? (
        <Panel title="Runtime exception">
          <StackTraceViewer frames={f.stack_trace} locations={f.locations} onSelect={(l, line) => setSel({ loc: l, line })} />
        </Panel>
      ) : <p className="faint">No stack trace was collected for this finding.</p>}

      <div className="split">
        <Panel title="Git context">{f.commit ? <GitContext commit={f.commit} /> : <NotAvailable what="Commit" why="No commit or deployment was correlated with this location." />}</Panel>
        <Panel title="Mechanism">
          {f.mechanism ? <p><EpistemicBadge kind="HYPOTHESIS" /> <Untrusted value={f.mechanism} max={1500} /></p> : <p className="muted">No mechanism was described.</p>}
          {f.next_step ? <p><EpistemicBadge kind="RECOMMENDED" /> <Untrusted value={f.next_step} max={300} /></p> : null}
          {f.unknowns.length ? <><h4>Unknown</h4><ul className="claims">{f.unknowns.map((u, k) => <li key={k}><EpistemicBadge kind="UNKNOWN" /> <Untrusted value={u} max={200} /></li>)}</ul></> : null}
          {f.alternatives.length ? <><h4>Alternative explanations</h4><ul className="claims">{f.alternatives.map((u, k) => <li key={k}><Untrusted value={u} max={160} /></li>)}</ul></> : null}
        </Panel>
      </div>
    </article>
  );
}

export function CodeRcaTab({ b }: { b: IncidentBundle }) {
  const { code, codeError } = b;
  return (
    <section aria-label="Code RCA" className="stack">
      <p className="note">Code-level RCA asks where in the code the runtime problem may originate. It is evidence for an engineer to inspect, not an instruction to change code.</p>
      {codeError ? <p role="alert" className="error">Code analysis: {describeError(codeError)}</p> : null}
      {code === undefined && !codeError ? <Skeleton label="code analysis" lines={5} /> : null}
      {code === null ? (
        <NotAvailable what="Code-level RCA" why={<>The backend does not provide code analysis for this incident (no <code>code-analysis</code> endpoint yet, see contract change request frontend-4). Cloud Doctor therefore cannot say which file, function or commit is involved. This is not evidence that the code is fine; use the RCA tab for the infrastructure-level diagnosis.</>} />
      ) : null}
      {code ? (
        <>
          {code.mock ? <p role="note" className="banner banner-degraded" data-testid="mock-banner"><strong>MOCK DATA.</strong> This analysis comes from the development mock server. It was not produced by Cloud Doctor.</p> : null}
          <p className="muted">Analysis by {code.origin === 'rule' ? 'deterministic rules' : 'LLM-assisted analysis'}{code.engine_version ? ` · engine ${code.engine_version}` : ''}. Source text below is untrusted data.</p>
          {code.findings.length === 0 ? <EmptyState title="Code analysis ran and returned no candidate location">Absence of a finding is not proof that the code is correct.</EmptyState> : null}
          {code.findings.map((f) => <Finding key={f.code_rca_id} incident={b.id} f={f} />)}
        </>
      ) : null}
    </section>
  );
}
