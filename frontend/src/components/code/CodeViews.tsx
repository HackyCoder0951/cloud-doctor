'use client';
// Evidence viewers for Code RCA. These are not an IDE: they show the suspect lines, why they were chosen, and the runtime
// evidence behind them. All source text, paths, commit subjects and diffs are untrusted data and render as inert text.
import { useState } from 'react';
import type { CodeFinding, CodeLocation, CommitInfo, StackFrame } from '@/lib/code-analysis';
import { Untrusted } from '@/lib/untrusted';

export function CodeViewer({ loc, focusLine }: { loc: CodeLocation; focusLine?: number }) {
  const hits = new Set(loc.highlight);
  return (
    <figure className="code" data-testid="code-viewer">
      <figcaption className="code__caption">
        <span className="mono"><Untrusted value={`${loc.file}:${loc.line_start}${loc.line_end !== loc.line_start ? `–${loc.line_end}` : ''}`} max={140} /></span>
        {loc.symbol ? <span className="muted"> · <Untrusted value={loc.symbol} max={80} /></span> : null}
        <span className="spacer" />
        <span className="faint">source is untrusted text</span>
      </figcaption>
      {loc.snippet.length === 0 ? <p className="muted code__none">No source lines were collected for this location.</p> : (
        <div className="code__scroll" role="region" aria-label={`Source ${loc.file}`} tabIndex={0}>
          {loc.snippet.map((l) => {
            const hit = hits.has(l.line);
            return (
              <div key={l.line} className="code__row" data-hit={hit ? 'true' : undefined} data-focus={focusLine === l.line ? 'true' : undefined}>
                <span className="code__mark" aria-hidden="true">{hit ? '▶' : ''}</span>
                <span className="code__no">{l.line}</span>
                <code className="code__text"><Untrusted value={l.text === '' ? ' ' : l.text} max={300} /></code>
                {hit ? <span className="sr-only"> suspect line</span> : null}
              </div>
            );
          })}
        </div>
      )}
    </figure>
  );
}

export function StackTraceViewer({ frames, locations, onSelect }: { frames: StackFrame[]; locations: CodeLocation[]; onSelect: (locIndex: number, line: number) => void }) {
  const [note, setNote] = useState<string | null>(null);
  return (
    <div className="trace" data-testid="stack-trace">
      <ol className="trace__list" aria-label="Stack trace">
        {frames.map((f, k) => {
          const at = locations.findIndex((l) => l.file === f.file && f.line >= l.line_start && f.line <= l.line_end);
          return (
            <li key={k}>
              <button type="button" className="trace__frame" onClick={() => { if (at >= 0) { setNote(null); onSelect(at, f.line); } else setNote(`Source for ${f.file}:${f.line} was not collected.`); }}>
                <span className="mono"><Untrusted value={`${f.file}:${f.line}`} max={110} /></span>
                {f.function ? <span className="muted"> <Untrusted value={`${f.function}()`} max={80} /></span> : null}
                {at < 0 ? <span className="faint"> · no source collected</span> : null}
              </button>
            </li>
          );
        })}
      </ol>
      {note ? <p role="status" className="muted"><Untrusted value={note} max={300} /></p> : null}
    </div>
  );
}

export function Diff({ file, lines }: { file: string; lines: { op: '+' | '-' | ' '; text: string }[] }) {
  return (
    <figure className="code diff" data-testid="diff">
      <figcaption className="code__caption mono"><Untrusted value={file} max={140} /></figcaption>
      <div className="code__scroll" role="region" aria-label={`Diff ${file}`} tabIndex={0}>
        {lines.map((l, k) => (
          <div key={k} className="code__row" data-op={l.op === '+' ? 'add' : l.op === '-' ? 'del' : 'ctx'}>
            <span className="code__mark" aria-hidden="true">{l.op === ' ' ? '' : l.op}</span>
            <span className="sr-only">{l.op === '+' ? 'added ' : l.op === '-' ? 'removed ' : 'unchanged '}</span>
            <code className="code__text"><Untrusted value={l.text === '' ? ' ' : l.text} max={300} /></code>
          </div>
        ))}
      </div>
    </figure>
  );
}

export function GitContext({ commit }: { commit: CommitInfo }) {
  const [showDiff, setShowDiff] = useState(false);
  return (
    <div className="git" data-testid="git-context">
      <p><span className="mono git__sha"><Untrusted value={commit.sha.slice(0, 12)} max={12} /></span> {commit.subject ? <Untrusted value={commit.subject} max={200} /> : <span className="muted">(no subject)</span>}</p>
      <p className="muted">
        {commit.author ? <>Author <Untrusted value={commit.author} max={80} /> · </> : null}
        {commit.committed_at ? <>Committed <span className="mono"><Untrusted value={commit.committed_at} max={40} /></span> · </> : null}
        {commit.files_changed.length} file{commit.files_changed.length === 1 ? '' : 's'} changed
      </p>
      {commit.files_changed.length > 0 ? <ul className="claims">{commit.files_changed.map((f, k) => <li key={k} className="mono"><Untrusted value={f} max={160} /></li>)}</ul> : null}
      <p className="row">
        <button type="button" className="secondary" disabled={commit.diff.length === 0} aria-expanded={showDiff} onClick={() => setShowDiff((v) => !v)}>{showDiff ? 'Hide diff' : 'View diff'}</button>
        <span className="faint">Blame and history are not collected.</span>
      </p>
      {showDiff ? commit.diff.map((d, k) => <Diff key={k} file={d.file} lines={d.lines} />) : null}
    </div>
  );
}

/** A band of the ranking score, deliberately not worded as confidence in the cause. "High" needs a strong status and two or more evidence items. */
export function rankingBand(f: Pick<CodeFinding, 'ranking' | 'evidence_ids' | 'status'>): 'High' | 'Medium' | 'Low' {
  if (f.ranking >= 0.8 && f.evidence_ids.length >= 2 && (f.status === 'strong_candidate' || f.status === 'confirmed')) return 'High';
  return f.ranking >= 0.5 ? 'Medium' : 'Low';
}
