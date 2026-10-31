// Code RCA data. The shape is proposed in docs/dev/contract-change-requests/frontend-4.md and is NOT yet
// in contracts/openapi.yaml, so nothing here is generated: the response is parsed defensively and anything
// malformed is dropped rather than repaired. The backend does not produce this data today; a 404 means
// "not available" and the UI says so (it never shows an empty success).

export type CodeStatus = 'candidate' | 'supported' | 'strong_candidate' | 'confirmed' | 'rejected' | 'unknown';
export const CODE_STATUSES: readonly CodeStatus[] = ['candidate', 'supported', 'strong_candidate', 'confirmed', 'rejected', 'unknown'];

export interface SnippetLine { line: number; text: string }
export interface CodeLocation {
  repository: string; branch?: string; commit?: string; file: string; line_start: number; line_end: number;
  symbol?: string; language?: string; snippet: SnippetLine[]; highlight: number[];
}
export interface StackFrame { file: string; line: number; function?: string }
export interface DiffLine { op: '+' | '-' | ' '; text: string }
export interface CommitInfo { sha: string; subject?: string; author?: string; committed_at?: string; files_changed: string[]; diff: { file: string; lines: DiffLine[] }[] }
export interface CodeFinding {
  code_rca_id: string; title: string; status: CodeStatus; ranking: number; service: string; mechanism?: string;
  evidence_ids: string[]; locations: CodeLocation[]; stack_trace: StackFrame[]; commit?: CommitInfo;
  runtime_symptoms: string[]; next_step?: string; unknowns: string[]; alternatives: string[];
}
export interface CodeAnalysis { incident_id: string; generated_at: string; origin: 'rule' | 'llm'; engine_version?: string; mock?: boolean; findings: CodeFinding[] }

export interface PlanPatch { file: string; lines: DiffLine[]; tests: { name: string; result: 'passed' | 'failed' | 'not_run' }[] }

const isObj = (x: unknown): x is Record<string, unknown> => !!x && typeof x === 'object' && !Array.isArray(x);
const str = (x: unknown, max = 600): string | undefined => (typeof x === 'string' && x.length > 0 ? x.slice(0, max) : undefined);
const int = (x: unknown): number | undefined => (typeof x === 'number' && Number.isInteger(x) && x >= 0 && x < 10_000_000 ? x : undefined);
const strs = (x: unknown, n = 50, max = 400): string[] => (Array.isArray(x) ? x.map((s) => str(s, max)).filter((s): s is string => !!s).slice(0, n) : []);
const EVIDENCE_ID = /^EV-[0-9]{3,}$/;

function parseLocation(x: unknown): CodeLocation | null {
  if (!isObj(x)) return null;
  const file = str(x.file, 300); const repository = str(x.repository, 120);
  const a = int(x.line_start); const b = int(x.line_end);
  if (!file || !repository || a === undefined || b === undefined || b < a) return null;
  const snippet: SnippetLine[] = [];
  if (Array.isArray(x.snippet)) {
    for (const s of x.snippet.slice(0, 200)) {
      if (!isObj(s)) continue;
      const line = int(s.line); const text = typeof s.text === 'string' ? s.text.slice(0, 400) : undefined;
      if (line !== undefined && text !== undefined) snippet.push({ line, text });
    }
  }
  const highlight = Array.isArray(x.highlight) ? x.highlight.map(int).filter((n): n is number => n !== undefined).slice(0, 50) : [];
  return { repository, branch: str(x.branch, 120), commit: str(x.commit, 64), file, line_start: a, line_end: b, symbol: str(x.symbol, 200), language: str(x.language, 30), snippet, highlight };
}

function parseDiff(x: unknown): DiffLine[] {
  if (!Array.isArray(x)) return [];
  const out: DiffLine[] = [];
  for (const d of x.slice(0, 200)) {
    if (!isObj(d) || (d.op !== '+' && d.op !== '-' && d.op !== ' ') || typeof d.text !== 'string') continue;
    out.push({ op: d.op, text: d.text.slice(0, 400) });
  }
  return out;
}

function parseCommit(x: unknown): CommitInfo | undefined {
  if (!isObj(x)) return undefined;
  const sha = str(x.sha, 64);
  if (!sha || !/^[0-9a-f]{7,64}$/.test(sha)) return undefined;
  const diff = Array.isArray(x.diff)
    ? x.diff.slice(0, 20).flatMap((d) => (isObj(d) && str(d.file, 300) ? [{ file: str(d.file, 300) as string, lines: parseDiff(d.lines) }] : []))
    : [];
  return { sha, subject: str(x.subject, 200), author: str(x.author, 120), committed_at: str(x.committed_at, 40), files_changed: strs(x.files_changed, 50, 300), diff };
}

function parseFinding(x: unknown): CodeFinding | null {
  if (!isObj(x)) return null;
  const id = str(x.code_rca_id, 40); const title = str(x.title, 300); const service = str(x.service, 60);
  const status = CODE_STATUSES.find((s) => s === x.status);
  const ranking = typeof x.ranking === 'number' && x.ranking >= 0 && x.ranking <= 1 ? x.ranking : undefined;
  if (!id || !title || !service || !status || ranking === undefined) return null;
  const stack: StackFrame[] = [];
  if (Array.isArray(x.stack_trace)) {
    for (const f of x.stack_trace.slice(0, 40)) {
      if (!isObj(f)) continue;
      const file = str(f.file, 300); const line = int(f.line);
      if (file && line !== undefined) stack.push({ file, line, function: str(f.function, 200) });
    }
  }
  return {
    code_rca_id: id, title, status, ranking, service, mechanism: str(x.mechanism, 2000),
    evidence_ids: strs(x.evidence_ids, 50, 20).filter((e) => EVIDENCE_ID.test(e)),
    locations: Array.isArray(x.locations) ? x.locations.slice(0, 10).map(parseLocation).filter((l): l is CodeLocation => l !== null) : [],
    stack_trace: stack, commit: parseCommit(x.commit), runtime_symptoms: strs(x.runtime_symptoms), next_step: str(x.next_step, 400),
    unknowns: strs(x.unknowns), alternatives: strs(x.alternatives),
  };
}

export function parseCodeAnalysis(raw: unknown): CodeAnalysis | null {
  if (!isObj(raw)) return null;
  const incident_id = str(raw.incident_id, 20); const generated_at = str(raw.generated_at, 40);
  if (!incident_id || !generated_at || !Array.isArray(raw.findings)) return null;
  return {
    incident_id, generated_at, origin: raw.origin === 'llm' ? 'llm' : 'rule', engine_version: str(raw.engine_version, 30), mock: raw.mock === true,
    findings: raw.findings.slice(0, 10).map(parseFinding).filter((f): f is CodeFinding => f !== null),
  };
}

/** A plan may carry a proposed patch. Absent or malformed means no patch panel, never a placeholder patch. */
export function parsePatch(plan: unknown): PlanPatch | null {
  if (!isObj(plan) || !isObj(plan.patch)) return null;
  const file = str(plan.patch.file, 300); const lines = parseDiff(plan.patch.lines);
  if (!file || lines.length === 0) return null;
  const tests: PlanPatch['tests'] = [];
  if (Array.isArray(plan.patch.tests)) {
    for (const t of plan.patch.tests.slice(0, 50)) {
      const name = isObj(t) ? str(t.name, 200) : undefined;
      if (isObj(t) && name && (t.result === 'passed' || t.result === 'failed' || t.result === 'not_run')) tests.push({ name, result: t.result });
    }
  }
  return { file, lines, tests };
}

export const RANKING_NOTE = 'Ranking is an evidence-weighted prioritisation score, not a probability.';
