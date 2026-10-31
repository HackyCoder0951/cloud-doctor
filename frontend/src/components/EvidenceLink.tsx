'use client';
import Link from 'next/link';
import { useEvidenceDrawer } from '@/components/EvidenceDrawer';
import { isEvidenceId, isIncidentId, Untrusted } from '@/lib/untrusted';

/** Links an evidence id, only if it matches the contract pattern. Inside the incident workspace it opens the evidence drawer;
 *  elsewhere it navigates to the row in the Evidence tab. */
export function EvidenceLink({ incident, id }: { incident: string; id: string }) {
  const drawer = useEvidenceDrawer();
  if (!isEvidenceId(id) || !isIncidentId(incident)) return <Untrusted value={id} max={20} />;
  return (
    <Link
      className="evlink"
      href={`/incidents/view/?id=${incident}&tab=evidence&ev=${id}`}
      onClick={drawer ? (ev) => { ev.preventDefault(); drawer.open(id); } : undefined}
    >{id}</Link>
  );
}

export function EvidenceLinks({ incident, ids }: { incident: string; ids: readonly string[] | undefined }) {
  if (!ids || ids.length === 0) return <span className="muted">none</span>;
  return <>{ids.map((id, i) => <span key={`${id}-${i}`}>{i > 0 ? ', ' : ''}<EvidenceLink incident={incident} id={id} /></span>)}</>;
}
