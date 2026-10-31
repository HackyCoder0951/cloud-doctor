'use client';
// Diagnosis and remediation for the incidents on screen (overview, queue). A lookup that fails leaves the field undefined,
// which the callers treat as "unknown", never as "nothing pending".
import { useEffect, useState } from 'react';
import { api, ApiError } from '@/api/client';
import type { Diagnosis, Incident, Remediation } from '@/api/types';

export interface Signals { diagnosis: Diagnosis | null | undefined; remediation: Remediation | undefined }

export function useIncidentSignals(ids: readonly string[], refreshKey: unknown = 0): Record<string, Signals> {
  const [signals, setSignals] = useState<Record<string, Signals>>({});
  const key = ids.join('|');
  useEffect(() => {
    let cancelled = false;
    if (ids.length === 0) { setSignals({}); return undefined; }
    void Promise.all(ids.map(async (id): Promise<[string, Signals]> => {
      const [diagnosis, remediation] = await Promise.all([
        api.getDiagnosis(id).catch((e: unknown) => (e instanceof ApiError && e.kind === 'not_found' ? null : undefined)),
        api.getRemediation(id).catch(() => undefined),
      ]);
      return [id, { diagnosis, remediation }];
    })).then((pairs) => { if (!cancelled) setSignals(Object.fromEntries(pairs)); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, refreshKey]);
  return signals;
}

/** Open incidents plus the few most recent others, so "recent recovery actions" has something to show. */
export function idsToWatch(list: Incident[] | undefined, extra = 6): string[] {
  if (!list) return [];
  const open = list.filter((i) => i.state !== 'recovered' && i.state !== 'closed');
  const recent = [...list].sort((a, b) => (a.opened_at < b.opened_at ? 1 : -1)).slice(0, extra);
  return [...new Set([...open, ...recent].map((i) => i.incident_id))];
}
