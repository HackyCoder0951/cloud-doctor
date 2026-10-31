import type { HealthState, IncidentState, MissingSignalState, Verdict } from '@/api/types';

const STATE_GLYPH: Record<HealthState, string> = { HEALTHY: '●', DEGRADED: '◐', UNHEALTHY: '✖', UNKNOWN: '?' };

/** Health state. UNKNOWN is deliberately unlike HEALTHY (dashed, grey, "?"): missing data is never healthy. */
export function StateBadge({ state }: { state: HealthState }) {
  return (
    <span className={`badge st-${state}`} data-state={state}>
      <span aria-hidden="true">{STATE_GLYPH[state]} </span>
      {state}
    </span>
  );
}

const MISSING: Record<Exclude<MissingSignalState, 'none'>, { label: string; help: string }> = {
  no_data_expected: { label: 'No data (expected)', help: 'No telemetry is expected from this service right now (for example idle or paused).' },
  no_data_unexpected: { label: 'No data (UNEXPECTED)', help: 'Telemetry should be arriving but is absent. Treated as a possible failure, never as healthy.' },
  collection_failed: { label: 'Collection FAILED', help: 'Cloud Doctor could not query telemetry for this service. Its real state is unknown.' },
};

export function MissingSignalBadge({ value, withHelp = false }: { value: MissingSignalState; withHelp?: boolean }) {
  if (value === 'none') return null;
  const m = MISSING[value];
  return (
    <span className={`badge ms-${value}`} data-missing-signal={value} title={m.help}>
      {m.label}
      {withHelp ? <span className="help"> — {m.help}</span> : null}
    </span>
  );
}

export function IncidentStateBadge({ state }: { state: IncidentState }) {
  return <span className={`badge is-${state}`} data-incident-state={state}>{state}</span>;
}

const VERDICT_LABEL: Record<Verdict, string> = {
  recovered: 'RECOVERED', partial: 'PARTIAL', failed: 'FAILED', regression: 'REGRESSION', relapse: 'RELAPSE', unverifiable: 'UNVERIFIABLE',
};
export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  return <span className={`badge vd-${verdict}`} data-verdict={verdict}>{VERDICT_LABEL[verdict]}</span>;
}

export function Tag({ kind, children }: { kind: string; children: React.ReactNode }) {
  return <span className={`badge tag tag-${kind}`}>{children}</span>;
}
