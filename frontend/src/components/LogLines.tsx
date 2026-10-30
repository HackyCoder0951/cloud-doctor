import { Untrusted } from '@/lib/untrusted';

export interface LogLine { t?: string; line: string; level?: string }

const MAX_LINES = 200;

/** Log lines are UNTRUSTED: each is rendered as a truncated text node, never parsed. */
export function LogLines({ lines, max = 400 }: { lines: LogLine[]; max?: number }) {
  const shown = lines.slice(0, MAX_LINES);
  return (
    <ol className="loglines" data-testid="loglines">
      {shown.map((l, i) => (
        <li key={i} className={l.level ? `lv-${String(l.level).replace(/[^a-z]/g, '')}` : undefined}>
          {l.t ? <time className="muted">{l.t} </time> : null}
          {l.level ? <span className="lvl">{String(l.level).slice(0, 8)} </span> : null}
          <Untrusted value={l.line} max={max} />
        </li>
      ))}
      {lines.length > MAX_LINES ? <li className="muted">… {lines.length - MAX_LINES} more lines not shown</li> : null}
    </ol>
  );
}
