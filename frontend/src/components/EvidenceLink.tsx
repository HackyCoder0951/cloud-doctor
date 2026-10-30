import Link from 'next/link';
import { isEvidenceId, isIncidentId, Untrusted } from '@/lib/untrusted';

/** Links an evidence id to its row in the Evidence tab, only if the id matches the contract pattern. */
export function EvidenceLink({ incident, id }: { incident: string; id: string }) {
  if (!isEvidenceId(id) || !isIncidentId(incident)) return <Untrusted value={id} max={20} />;
  return <Link className="evlink" href={`/incidents/view/?id=${incident}&tab=evidence&ev=${id}`}>{id}</Link>;
}

export function EvidenceLinks({ incident, ids }: { incident: string; ids: readonly string[] | undefined }) {
  if (!ids || ids.length === 0) return <span className="muted">none</span>;
  return <>{ids.map((id, i) => <span key={`${id}-${i}`}>{i > 0 ? ', ' : ''}<EvidenceLink incident={incident} id={id} /></span>)}</>;
}
