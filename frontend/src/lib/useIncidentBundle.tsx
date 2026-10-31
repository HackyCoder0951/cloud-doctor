'use client';
// One place that loads everything the incident workspace header, summary and action rail need,
// so those parts agree with each other and the API is not asked the same question five times.
// `null` means "the API answered: there is none" (404). `undefined` means "not loaded yet".
import { createContext, useContext, useMemo, type ReactNode } from 'react';
import { api, ApiError } from '@/api/client';
import type { Diagnosis, Evidence, Incident, Remediation, Verification } from '@/api/types';
import type { CodeAnalysis } from '@/lib/code-analysis';
import { useLiveReload } from '@/components/Live';
import { useApi } from '@/lib/useApi';

export interface IncidentBundle {
  id: string;
  incident: Incident | undefined;
  incidentError: unknown;
  diagnosis: Diagnosis | null | undefined;
  remediation: Remediation | undefined;
  verification: Verification[] | undefined;
  evidence: Evidence[] | undefined;
  /** null: the backend does not provide code analysis (404). undefined: not loaded, or the request failed. */
  code: CodeAnalysis | null | undefined;
  codeError: unknown;
  loading: boolean;
  reload: () => void;
}

const BundleContext = createContext<IncidentBundle | null>(null);
export const useIncidentBundle = (): IncidentBundle | null => useContext(BundleContext);

const orNull = <T,>(p: Promise<T>): Promise<T | null> => p.catch((e: unknown) => { if (e instanceof ApiError && e.kind === 'not_found') return null; throw e; });

export function IncidentBundleProvider({ id, children }: { id: string; children: ReactNode }) {
  const incident = useApi(() => api.getIncident(id), [id]);
  const diagnosis = useApi(() => orNull(api.getDiagnosis(id)), [id]);
  const remediation = useApi(() => api.getRemediation(id), [id]);
  const verification = useApi(() => api.getVerification(id), [id]);
  const evidence = useApi(() => api.getEvidence(id), [id]);
  const code = useApi(() => api.getCodeAnalysis(id), [id]);
  const reload = () => { incident.reload(); diagnosis.reload(); remediation.reload(); verification.reload(); evidence.reload(); code.reload(); };
  useLiveReload(reload, (e) => e.incident_id === id);

  const value = useMemo<IncidentBundle>(() => ({
    id,
    incident: incident.data,
    incidentError: incident.error,
    diagnosis: diagnosis.data,
    remediation: remediation.data,
    verification: verification.data,
    evidence: evidence.data,
    code: code.data,
    codeError: code.error,
    loading: incident.loading && !incident.data,
    reload,
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [id, incident.data, incident.error, incident.loading, diagnosis.data, remediation.data, verification.data, evidence.data, code.data, code.error]);
  return <BundleContext.Provider value={value}>{children}</BundleContext.Provider>;
}
