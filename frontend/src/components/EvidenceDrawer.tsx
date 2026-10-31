'use client';
// Evidence detail without leaving the reasoning. Any <EvidenceLink> inside a provider opens it; outside one the link
// still navigates to the Evidence tab, so the link works without JavaScript state.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import type { Evidence, Hypothesis } from '@/api/types';
import { fmtTime } from '@/components/common';
import { MissingSignalBadge } from '@/components/badges';
import { Payload } from '@/components/tabs/EvidenceTab';
import { Pill, TrustBadge } from '@/components/ui';
import { evidenceRole, topHypothesis, trustOf, type EvidenceRole } from '@/lib/incident-view';
import { Untrusted } from '@/lib/untrusted';
import { useIncidentBundle } from '@/lib/useIncidentBundle';

interface DrawerApi { open: (id: string) => void }
const DrawerContext = createContext<DrawerApi | null>(null);
export const useEvidenceDrawer = (): DrawerApi | null => useContext(DrawerContext);

const ROLE: Record<EvidenceRole, { tone: 'ok' | 'bad' | 'unknown'; glyph: string; label: string }> = {
  supporting: { tone: 'ok', glyph: '✓', label: 'SUPPORTING' },
  contradicting: { tone: 'bad', glyph: '✕', label: 'CONTRADICTING' },
  context: { tone: 'unknown', glyph: '·', label: 'CONTEXT' },
};
export const RolePill = ({ role }: { role: EvidenceRole }) => <Pill tone={ROLE[role].tone} glyph={ROLE[role].glyph}>{ROLE[role].label}</Pill>;

export function EvidenceFacts({ e, role }: { e: Evidence; role: EvidenceRole }) {
  return (
    <dl className="facts">
      <dt>Type</dt><dd>{e.type}</dd>
      <dt>Source</dt><dd><Untrusted value={e.source} max={40} /> · <Untrusted value={e.service} max={40} /></dd>
      <dt>Observed</dt><dd className="mono">{fmtTime(e.observed_at)}</dd>
      <dt>Observation</dt><dd><Untrusted value={e.summary ?? '(no summary reported)'} max={400} /></dd>
      <dt>Trust</dt><dd><TrustBadge trust={trustOf(e)} /></dd>
      <dt>Role</dt><dd><RolePill role={role} /></dd>
      <dt>Status</dt><dd><span className={`badge es-${e.status}`}>{e.status}</span> {e.missing_signal_state ? <MissingSignalBadge value={e.missing_signal_state} /> : null}</dd>
    </dl>
  );
}

/** Compact evidence card: the observation first, bookkeeping (query, hash, payload) behind the drawer. */
export function EvidenceCard({ e, role, onOpen }: { e: Evidence; role: EvidenceRole; onOpen: (id: string) => void }) {
  return (
    <article className="evcard" data-role={role} data-testid={`evcard-${e.evidence_id}`}>
      <header className="row">
        <button type="button" className="chip-button mono" onClick={() => onOpen(e.evidence_id)} aria-label={`Open evidence ${e.evidence_id}`}>{e.evidence_id}</button>
        <RolePill role={role} />
        <TrustBadge trust={trustOf(e)} />
        <span className="spacer" />
        <span className="muted mono">{fmtTime(e.observed_at)}</span>
      </header>
      <p className="evcard__obs"><Untrusted value={e.summary ?? '(no summary reported)'} max={240} /></p>
      <p className="muted">{e.type} · <Untrusted value={e.source} max={30} /> · <Untrusted value={e.service} max={40} /></p>
    </article>
  );
}

function Drawer({ evidence, id, hypothesis, onClose }: { evidence: Evidence[] | undefined; id: string; hypothesis: Hypothesis | undefined; onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const e = evidence?.find((x) => x.evidence_id === id);
  useEffect(() => {
    const returnTo = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const onKey = (ev: KeyboardEvent) => { if (ev.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('keydown', onKey); returnTo?.focus?.(); };
  }, [onClose]);
  return (
    <aside className="drawer" role="dialog" aria-label={`Evidence ${id}`} data-testid="evidence-drawer">
      <header className="row">
        <h2 className="drawer__title mono">{id}</h2>
        <span className="spacer" />
        <button type="button" className="ghost" ref={closeRef} onClick={onClose}>Close</button>
      </header>
      {!evidence ? <p className="muted">Loading evidence…</p> : !e ? (
        <p role="note" className="note">Evidence {id} is not in the set collected for this incident. A reference to evidence that does not exist cannot support a claim.</p>
      ) : (
        <>
          <EvidenceFacts e={e} role={evidenceRole(id, hypothesis)} />
          <h4>Query</h4>
          <p className="mono untrusted-block"><Untrusted value={e.query} max={400} /></p>
          <h4>Payload</h4>
          <Payload e={e} />
          <p className="muted mono">sha256 {e.payload_hash}</p>
        </>
      )}
    </aside>
  );
}

export function EvidenceDrawerProvider({ children }: { children: ReactNode }) {
  const bundle = useIncidentBundle();
  const [selected, setSelected] = useState<string | null>(null);
  const open = useCallback((id: string) => setSelected(id), []);
  const close = useCallback(() => setSelected(null), []);
  const value = useMemo<DrawerApi>(() => ({ open }), [open]);
  const top = topHypothesis(bundle?.diagnosis ?? undefined);
  return (
    <DrawerContext.Provider value={value}>
      {children}
      {selected ? <Drawer evidence={bundle?.evidence} id={selected} hypothesis={top} onClose={close} /> : null}
    </DrawerContext.Provider>
  );
}
