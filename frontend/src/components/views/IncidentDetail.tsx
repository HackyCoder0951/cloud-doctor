'use client';
import Link from 'next/link';
import { api, ApiError } from '@/api/client';
import { ErrorNote, fmtTime, Loading } from '@/components/common';
import { IncidentStateBadge } from '@/components/badges';
import { useLiveReload } from '@/components/Live';
import { DiagnosisTab } from '@/components/tabs/DiagnosisTab';
import { EvidenceTab } from '@/components/tabs/EvidenceTab';
import { RemediationTab } from '@/components/tabs/RemediationTab';
import { ReportTab } from '@/components/tabs/ReportTab';
import { TimelineTab } from '@/components/tabs/TimelineTab';
import { VerificationTab } from '@/components/tabs/VerificationTab';
import { isServiceName, Untrusted } from '@/lib/untrusted';
import { useApi } from '@/lib/useApi';

export const TABS = ['timeline', 'evidence', 'diagnosis', 'remediation', 'verification', 'report'] as const;
export type TabId = (typeof TABS)[number];
export const isTab = (s: string | null | undefined): s is TabId => !!s && (TABS as readonly string[]).includes(s);

export function IncidentDetail({ incident, tab, evidenceFocus, onTab }: { incident: string; tab: TabId; evidenceFocus?: string; onTab: (t: TabId) => void }) {
  const { data, error, loading, reload } = useApi(() => api.getIncident(incident), [incident]);
  useLiveReload(reload, (e) => e.incident_id === incident && (e.type === 'incident.updated' || e.type === 'incident.opened'));
  const notFound = error instanceof ApiError && error.kind === 'not_found';
  return (
    <>
      <p><Link href="/incidents/">← Incidents</Link></p>
      <h1>{incident}</h1>
      {notFound ? <p role="alert" className="error">Incident not found.</p> : <ErrorNote error={error} what="Incident" />}
      {loading && !data ? <Loading what="incident" /> : null}
      {data ? (
        <section className="card summary" aria-label="Incident summary">
          <p className="row">
            <IncidentStateBadge state={data.state} /> <span>severity: <strong>{data.severity}</strong></span>
            <span>opened {fmtTime(data.opened_at)}</span>{data.closed_at ? <span>closed {fmtTime(data.closed_at)}</span> : null}
            {data.outcome ? <span>outcome: <strong>{data.outcome}</strong></span> : null}
            <span>root cause confirmed: <strong>{String(!!data.root_cause_confirmed)}</strong></span>
            {data.run_id ? <span>harness run: <Untrusted value={data.run_id} max={60} /></span> : null}
          </p>
          <p>Services: {data.services.map((s) => (isServiceName(s) ? <Link key={s} href={`/services/view/?name=${s}`}>{s} </Link> : <Untrusted key={s} value={s} max={40} />))}</p>
          <ul>{data.symptoms.map((s, i) => <li key={i}><Untrusted value={s} max={200} /></li>)}</ul>
        </section>
      ) : null}
      <div role="tablist" aria-label="Incident sections" className="tabs">
        {TABS.map((t) => (
          <button key={t} type="button" role="tab" id={`tab-${t}`} aria-selected={tab === t} aria-controls="tabpanel" className={tab === t ? 'active' : undefined} onClick={() => onTab(t)}>{t}</button>
        ))}
      </div>
      <div role="tabpanel" id="tabpanel" aria-labelledby={`tab-${tab}`}>
        {tab === 'timeline' ? <TimelineTab incident={incident} /> : null}
        {tab === 'evidence' ? <EvidenceTab incident={incident} focus={evidenceFocus} /> : null}
        {tab === 'diagnosis' ? <DiagnosisTab incident={incident} /> : null}
        {tab === 'remediation' ? <RemediationTab incident={incident} /> : null}
        {tab === 'verification' ? <VerificationTab incident={incident} /> : null}
        {tab === 'report' ? <ReportTab incident={incident} /> : null}
      </div>
    </>
  );
}
