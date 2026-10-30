// Rendering of UNTRUSTED strings (evidence, log lines, claims, symptoms, error text).
// Everything is returned as a React text node: no HTML parsing, no href/src built from the value.
// Very long values are truncated and control / bidi-override characters are made visible so they
// cannot reorder or hide text (trojan-source style tricks).

export const DEFAULT_MAX = 600;

// C0 controls except \t \n, DEL, C1 controls, bidi embeddings/overrides/isolates, zero-width chars, BOM.
const HIDDEN = /[\u0000-\u0008\u000B-\u001F\u007F-\u009F​-‏‪-‮⁠-⁩﻿]/g;

export interface SafeText {
  text: string;
  truncated: boolean;
  originalLength: number;
}

export function safeText(value: unknown, max: number = DEFAULT_MAX): SafeText {
  const raw = typeof value === 'string' ? value : value === null || value === undefined ? '' : String(value);
  const visible = raw.replace(HIDDEN, (ch) => `\\u${ch.charCodeAt(0).toString(16).padStart(4, '0')}`);
  const truncated = visible.length > max;
  return { text: truncated ? visible.slice(0, max) : visible, truncated, originalLength: raw.length };
}

export function Untrusted({ value, max = DEFAULT_MAX, className }: { value: unknown; max?: number; className?: string }) {
  const s = safeText(value, max);
  return (
    <span className={className ? `untrusted ${className}` : 'untrusted'} data-untrusted="true">
      {s.text}
      {s.truncated ? <span className="trunc"> … [truncated, {s.originalLength} chars]</span> : null}
    </span>
  );
}

/** JSON of an untrusted object as truncated text (for <pre>). */
export function jsonText(value: unknown, max = 4000): SafeText {
  let s: string;
  try {
    s = JSON.stringify(value, null, 2) ?? '';
  } catch {
    s = '[unserialisable]';
  }
  return safeText(s, max);
}

// Identifiers are only ever turned into links after matching the contract patterns.
export const INCIDENT_ID_RE = /^INC-[0-9]{4,}$/;
export const EVIDENCE_ID_RE = /^EV-[0-9]{3,}$/;
export const PLAN_ID_RE = /^PL-[0-9]{4,}$/;
export const SERVICE_RE = /^[a-z][a-z0-9-]{1,40}$/;
export const isIncidentId = (s: unknown): s is string => typeof s === 'string' && INCIDENT_ID_RE.test(s);
export const isEvidenceId = (s: unknown): s is string => typeof s === 'string' && EVIDENCE_ID_RE.test(s);
export const isServiceName = (s: unknown): s is string => typeof s === 'string' && SERVICE_RE.test(s);
