'use client';
import Link from 'next/link';
import type { KeyboardEvent } from 'react';
import { ApiError } from '@/api/client';
import { ErrorNote } from '@/components/common';
import { EvidenceDrawerProvider } from '@/components/EvidenceDrawer';
import { ActionRail, IncidentHeader } from '@/components/incident/Workspace';
import { CodeRcaTab } from '@/components/tabs/CodeRcaTab';
import { DiagnosisTab } from '@/components/tabs/DiagnosisTab';
import { EvidenceTab } from '@/components/tabs/EvidenceTab';
import { RemediationTab } from '@/components/tabs/RemediationTab';
import { ReportTab } from '@/components/tabs/ReportTab';
import { SummaryTab } from '@/components/tabs/SummaryTab';
import { TimelineTab } from '@/components/tabs/TimelineTab';
import { VerificationTab } from '@/components/tabs/VerificationTab';
import { Skeleton } from '@/components/ui';
import { IncidentBundleProvider, useIncidentBundle } from '@/lib/useIncidentBundle';

// Order follows the investigation: what happened, when, on what evidence, why, where in the code, what to do, did it work, the record.
// Ids stay stable because they appear in URLs ("diagnosis" is labelled RCA).
export const TABS = ['summary', 'timeline', 'evidence', 'diagnosis', 'code', 'remediation', 'verification', 'report'] as const;
export type TabId = (typeof TABS)[number];
export const TAB_LABEL: Record<TabId, string> = {
  summary: 'Summary', timeline: 'Timeline', evidence: 'Evidence', diagnosis: 'RCA', code: 'Code RCA', remediation: 'Remediation', verification: 'Verification', report: 'Report',
};
export const isTab = (s: string | null | undefined): s is TabId => !!s && (TABS as readonly string[]).includes(s);

function Workspace({ incident, tab, evidenceFocus, onTab }: { incident: string; tab: TabId; evidenceFocus?: string; onTab: (t: TabId) => void }) {
  const b = useIncidentBundle();
  if (!b) return null;
  const notFound = b.incidentError instanceof ApiError && b.incidentError.kind === 'not_found';
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const at = TABS.indexOf(tab);
    const next = e.key === 'ArrowRight' ? TABS[(at + 1) % TABS.length] : e.key === 'ArrowLeft' ? TABS[(at - 1 + TABS.length) % TABS.length] : e.key === 'Home' ? TABS[0] : e.key === 'End' ? TABS[TABS.length - 1] : undefined;
    if (next) { e.preventDefault(); onTab(next); document.getElementById(`tab-${next}`)?.focus(); }
  };
  return (
    <>
      <p><Link href="/incidents/">← Incidents</Link></p>
      {notFound ? <p role="alert" className="error">Incident not found.</p> : <ErrorNote error={b.incidentError} what="Incident" />}
      {b.loading ? <Skeleton label="incident" lines={4} /> : null}
      <IncidentHeader b={b} />
      <div className="workspace">
        <div className="workspace__main">
          <div role="tablist" aria-label="Incident sections" className="tabs" onKeyDown={onKey}>
            {TABS.map((t) => (
              <button key={t} type="button" role="tab" id={`tab-${t}`} aria-selected={tab === t} aria-controls="tabpanel" tabIndex={tab === t ? 0 : -1} className={tab === t ? 'active' : undefined} onClick={() => onTab(t)}>{TAB_LABEL[t]}</button>
            ))}
          </div>
          <div role="tabpanel" id="tabpanel" aria-labelledby={`tab-${tab}`}>
            {tab === 'summary' ? <SummaryTab b={b} onTab={onTab} /> : null}
            {tab === 'timeline' ? <TimelineTab incident={incident} /> : null}
            {tab === 'evidence' ? <EvidenceTab incident={incident} focus={evidenceFocus} /> : null}
            {tab === 'diagnosis' ? <DiagnosisTab incident={incident} onTab={onTab} /> : null}
            {tab === 'code' ? <CodeRcaTab b={b} /> : null}
            {tab === 'remediation' ? <RemediationTab incident={incident} /> : null}
            {tab === 'verification' ? <VerificationTab incident={incident} /> : null}
            {tab === 'report' ? <ReportTab incident={incident} /> : null}
          </div>
        </div>
        <ActionRail b={b} onTab={onTab} />
      </div>
    </>
  );
}

export function IncidentDetail({ incident, tab, evidenceFocus, onTab }: { incident: string; tab: TabId; evidenceFocus?: string; onTab: (t: TabId) => void }) {
  return (
    <IncidentBundleProvider id={incident}>
      <EvidenceDrawerProvider>
        <Workspace incident={incident} tab={tab} evidenceFocus={evidenceFocus} onTab={onTab} />
      </EvidenceDrawerProvider>
    </IncidentBundleProvider>
  );
}
