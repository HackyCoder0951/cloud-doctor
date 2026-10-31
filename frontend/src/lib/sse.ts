// EventSource wrapper with a visible connection state and reconnect.
// The browser reconnects on its own after a dropped connection (sending Last-Event-ID). When the
// browser gives up (readyState CLOSED, e.g. after an HTTP error) we open a new EventSource with
// exponential backoff. A fresh EventSource cannot set Last-Event-ID, so after EVERY reconnect the
// client asks consumers to resync (refetch) instead of relying on replay.
import type { StreamEvent } from '@/api/types';

export type ConnState = 'connecting' | 'open' | 'reconnecting' | 'closed';

const TYPES = new Set(['service.health', 'incident.opened', 'incident.updated', 'timeline.event', 'plan.created', 'decision.recorded', 'execution.finished', 'verification.finished', 'status.changed']);

/** Returns the event if it has the StreamEvent shape; unknown or malformed messages are ignored. */
export function parseStreamEvent(raw: string): StreamEvent | null {
  try {
    const v: unknown = JSON.parse(raw);
    if (!v || typeof v !== 'object') return null;
    const o = v as Record<string, unknown>;
    if (typeof o.type !== 'string' || !TYPES.has(o.type) || typeof o.at !== 'string') return null;
    if (o.incident_id !== undefined && typeof o.incident_id !== 'string') return null;
    if (o.service !== undefined && typeof o.service !== 'string') return null;
    return o as unknown as StreamEvent;
  } catch {
    return null;
  }
}

export interface StreamClientOptions {
  url: string;
  onEvent: (e: StreamEvent) => void;
  onState: (s: ConnState) => void;
  onResync: () => void;
  EventSourceImpl?: typeof EventSource;
  backoffMs?: (attempt: number) => number;
}

export const defaultBackoff = (attempt: number) => Math.min(30_000, 1000 * 2 ** Math.max(0, attempt - 1));

export class StreamClient {
  private es: EventSource | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private attempt = 0;
  private everOpened = false;
  private stopped = true;

  constructor(private readonly o: StreamClientOptions) {}

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    this.open();
  }

  stop(): void {
    this.stopped = true;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.es?.close();
    this.es = null;
    this.o.onState('closed');
  }

  private open(): void {
    const Impl = this.o.EventSourceImpl ?? globalThis.EventSource;
    if (!Impl) {
      this.o.onState('closed');
      return;
    }
    this.o.onState(this.everOpened || this.attempt > 0 ? 'reconnecting' : 'connecting');
    const es = new Impl(this.o.url, { withCredentials: true });
    this.es = es;
    es.onopen = () => {
      if (this.es !== es) return;
      this.attempt = 0;
      this.o.onState('open');
      if (this.everOpened) this.o.onResync();
      this.everOpened = true;
    };
    es.onmessage = (m: MessageEvent) => {
      if (this.es !== es) return;
      const ev = typeof m.data === 'string' ? parseStreamEvent(m.data) : null;
      if (ev) this.o.onEvent(ev);
    };
    es.onerror = () => {
      if (this.es !== es || this.stopped) return;
      this.o.onState('reconnecting');
      if (es.readyState === 2 /* CLOSED: the browser will not retry */) {
        es.close();
        this.es = null;
        this.attempt += 1;
        const delay = (this.o.backoffMs ?? defaultBackoff)(this.attempt);
        this.timer = setTimeout(() => {
          this.timer = null;
          if (!this.stopped) this.open();
        }, delay);
      }
    };
  }
}
