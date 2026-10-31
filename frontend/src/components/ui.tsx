// Small presentational building blocks. Colour is never the only signal: each tone also has a glyph and a word.
import type { ReactNode } from 'react';
import type { Epistemic, Trust } from '@/lib/incident-view';

export type Tone = 'ok' | 'warn' | 'bad' | 'info' | 'ai' | 'accent' | 'unknown';

export function Pill({ tone = 'unknown', glyph, children, title, testId }: { tone?: Tone; glyph?: string; children: ReactNode; title?: string; testId?: string }) {
  return (
    <span className="pill" data-tone={tone} title={title} data-testid={testId}>
      {glyph ? <span aria-hidden="true">{glyph}</span> : null}
      {children}
    </span>
  );
}

const SEV: Record<string, { tone: Tone; glyph: string }> = {
  critical: { tone: 'bad', glyph: '◆' }, high: { tone: 'bad', glyph: '▲' }, medium: { tone: 'warn', glyph: '■' }, low: { tone: 'unknown', glyph: '●' },
};
export function SeverityBadge({ severity }: { severity: string }) {
  const s = SEV[severity] ?? { tone: 'unknown' as Tone, glyph: '?' };
  return <Pill tone={s.tone} glyph={s.glyph} testId="severity">{severity.toUpperCase()}</Pill>;
}

const EPI: Record<Epistemic, { tone: Tone; glyph: string; help: string }> = {
  OBSERVED: { tone: 'info', glyph: '◉', help: 'Directly measured or seen in collected evidence.' },
  INFERRED: { tone: 'ai', glyph: '∴', help: 'Reasoned from observations (for example a temporal correlation). Not directly measured.' },
  HYPOTHESIS: { tone: 'ai', glyph: '?', help: 'A candidate explanation. Ranked, not proven.' },
  RECOMMENDED: { tone: 'accent', glyph: '→', help: 'A proposal. Policy decides whether it can run.' },
  CONFIRMED: { tone: 'ok', glyph: '✓', help: 'Supported by verification, not just by ranking.' },
  UNKNOWN: { tone: 'unknown', glyph: '?', help: 'Cloud Doctor could not establish this.' },
};
export function EpistemicBadge({ kind }: { kind: Epistemic }) {
  const e = EPI[kind];
  return <Pill tone={e.tone} glyph={e.glyph} title={e.help} testId={`epi-${kind}`}>{kind}</Pill>;
}

export function TrustBadge({ trust }: { trust: Trust }) {
  return trust === 'untrusted_text'
    ? <Pill tone="warn" glyph="⚠" title="Text from a monitored system. It may be hostile and is never interpreted.">UNTRUSTED TEXT</Pill>
    : <Pill tone="ok" glyph="◈" title="A value collected by Cloud Doctor's own deterministic collectors.">SYSTEM TELEMETRY</Pill>;
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty" role="note">
      <strong>{title}</strong>
      {children ? <div className="muted">{children}</div> : null}
    </div>
  );
}

/** The honest answer to "the backend does not provide this". Distinct from an empty result: it says why. */
export function NotAvailable({ what, why }: { what: string; why: ReactNode }) {
  return (
    <div className="empty empty--na" role="note" data-testid="not-available">
      <strong><span aria-hidden="true">∅ </span>{what}: not available</strong>
      <div className="muted">{why}</div>
    </div>
  );
}

export function Skeleton({ lines = 3, label }: { lines?: number; label: string }) {
  return (
    <div className="skeleton" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading {label}…</span>
      {Array.from({ length: lines }, (_, i) => <span key={i} className="skeleton__bar" data-w={i % 3} />)}
    </div>
  );
}

export function Panel({ title, aside, children, id, tone }: { title: string; aside?: ReactNode; children: ReactNode; id?: string; tone?: Tone }) {
  return (
    <section className="panel" id={id} data-tone={tone} aria-label={title}>
      <header className="panel__header"><h3 className="panel__title">{title}</h3><span className="spacer" />{aside}</header>
      <div className="panel__body">{children}</div>
    </section>
  );
}

/** A meter as a bar plus the number, so it never relies on fill colour alone. */
export function Meter({ value, label, tone = 'accent' }: { value: number; label: string; tone?: Tone }) {
  const v = Math.max(0, Math.min(1, value));
  return (
    <span className="meter" data-tone={tone}>
      <meter min={0} max={1} value={v} aria-label={label} />
      <span className="mono">{v.toFixed(2)}</span>
    </span>
  );
}
