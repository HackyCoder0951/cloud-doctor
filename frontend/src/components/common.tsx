import { describeError } from '@/api/client';

export function ErrorNote({ error, what }: { error: unknown; what?: string }) {
  if (!error) return null;
  return <p role="alert" className="error">{what ? `${what}: ` : ''}{describeError(error)}</p>;
}

export function Loading({ what }: { what: string }) {
  return <p className="muted" aria-live="polite">Loading {what}…</p>;
}

export function fmtTime(iso: string | undefined): string {
  if (!iso) return '—';
  return iso.replace('T', ' ').replace(/\.\d+Z$/, 'Z');
}

export function fmtNum(v: number | undefined, digits = 3): string {
  if (v === undefined) return '—';
  return Number.isInteger(v) ? String(v) : v.toFixed(digits).replace(/0+$/, '').replace(/\.$/, '');
}

/** Seconds between two ISO timestamps (collected_at - event_time), or null. */
export function lagSeconds(eventTime: string, collectedAt: string): number | null {
  const a = Date.parse(eventTime);
  const b = Date.parse(collectedAt);
  return Number.isFinite(a) && Number.isFinite(b) ? Math.round((b - a) / 1000) : null;
}
