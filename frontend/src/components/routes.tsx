'use client';
// Thin route wrappers: a static export cannot use dynamic path segments for runtime ids, so ids and
// filters travel in the query string. Every value is validated against the contract patterns first.
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense } from 'react';
import type { IncidentState } from '@/api/types';
import { AuditView } from '@/components/views/AuditView';
import { IncidentDetail, isTab } from '@/components/views/IncidentDetail';
import { IncidentsList, INCIDENT_STATES } from '@/components/views/IncidentsList';
import { ServiceDetail } from '@/components/views/ServiceDetail';
import { INCIDENT_ID_RE, isEvidenceId, isServiceName } from '@/lib/untrusted';

function IncidentsRoute() {
  const router = useRouter();
  const sp = useSearchParams();
  const raw = sp.get('state');
  const state = INCIDENT_STATES.includes(raw as IncidentState) ? (raw as IncidentState) : undefined;
  return <IncidentsList state={state} onStateChange={(s) => router.replace(s ? `/incidents/?state=${s}` : '/incidents/')} />;
}

function IncidentRoute() {
  const router = useRouter();
  const sp = useSearchParams();
  const id = sp.get('id') ?? '';
  const t = sp.get('tab');
  const ev = sp.get('ev');
  if (!INCIDENT_ID_RE.test(id)) return <p role="alert" className="error">Missing or invalid incident id.</p>;
  return <IncidentDetail incident={id} tab={isTab(t) ? t : 'summary'} evidenceFocus={isEvidenceId(ev) ? ev : undefined} onTab={(next) => router.replace(`/incidents/view/?id=${id}&tab=${next}`)} />;
}

function ServiceRoute() {
  const name = useSearchParams().get('name') ?? '';
  if (!isServiceName(name)) return <p role="alert" className="error">Missing or invalid service name.</p>;
  return <ServiceDetail service={name} />;
}

function AuditRoute() {
  const router = useRouter();
  const raw = useSearchParams().get('incident') ?? '';
  const incident = INCIDENT_ID_RE.test(raw) ? raw : undefined;
  return <AuditView key={incident ?? 'all'} incident={incident} onIncidentChange={(id) => router.replace(id ? `/audit/?incident=${id}` : '/audit/')} />;
}

export const IncidentsPage = () => <Suspense fallback={<p className="muted">Loading…</p>}><IncidentsRoute /></Suspense>;
export const IncidentPage = () => <Suspense fallback={<p className="muted">Loading…</p>}><IncidentRoute /></Suspense>;
export const ServicePage = () => <Suspense fallback={<p className="muted">Loading…</p>}><ServiceRoute /></Suspense>;
export const AuditPage = () => <Suspense fallback={<p className="muted">Loading…</p>}><AuditRoute /></Suspense>;
