import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { LiveProvider, useLiveReload } from '@/components/Live';
import { ConnectionBadge } from '@/components/AppShell';
import { defaultBackoff, parseStreamEvent, StreamClient, type ConnState } from '@/lib/sse';

class FakeES {
  static all: FakeES[] = [];
  static CLOSED = 2;
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((m: { data: unknown }) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  constructor(public url: string, public init?: EventSourceInit) { FakeES.all.push(this); }
  close() { this.closed = true; this.readyState = 2; }
  open() { this.readyState = 1; this.onopen?.(); }
  send(data: unknown) { this.onmessage?.({ data: typeof data === 'string' ? data : JSON.stringify(data) }); }
  failTemporarily() { this.readyState = 0; this.onerror?.(); } // the browser retries by itself
  failPermanently() { this.readyState = 2; this.onerror?.(); } // the browser gave up
}
const ES = FakeES as unknown as typeof EventSource;
const EVENT = { type: 'service.health', at: '2026-11-02T09:00:00Z', service: 'api' };

beforeEach(() => { FakeES.all = []; vi.useFakeTimers(); });
afterEach(() => vi.useRealTimers());

function make() {
  const states: ConnState[] = [];
  const events: unknown[] = [];
  const resync = vi.fn();
  const client = new StreamClient({ url: '/api/v1/stream', EventSourceImpl: ES, onState: (s) => states.push(s), onEvent: (e) => events.push(e), onResync: resync, backoffMs: (n) => n * 1000 });
  return { client, states, events, resync };
}

describe('parseStreamEvent', () => {
  it('accepts valid events and rejects malformed or unknown ones', () => {
    expect(parseStreamEvent(JSON.stringify(EVENT))).toMatchObject({ type: 'service.health' });
    expect(parseStreamEvent('not json')).toBeNull();
    expect(parseStreamEvent('null')).toBeNull();
    expect(parseStreamEvent(JSON.stringify({ type: 'evil', at: 'x' }))).toBeNull();
    expect(parseStreamEvent(JSON.stringify({ type: 'service.health' }))).toBeNull();
    expect(parseStreamEvent(JSON.stringify({ ...EVENT, incident_id: 5 }))).toBeNull();
  });
  it('backs off exponentially up to 30 s', () => {
    expect([1, 2, 3, 4, 10].map(defaultBackoff)).toEqual([1000, 2000, 4000, 8000, 30000]);
  });
});

describe('StreamClient', () => {
  it('connects with credentials, reports state and delivers events', () => {
    const { client, states, events } = make();
    client.start();
    expect(states).toEqual(['connecting']);
    const es = FakeES.all[0]!;
    expect(es.url).toBe('/api/v1/stream');
    expect(es.init).toEqual({ withCredentials: true });
    es.open();
    es.send(EVENT);
    es.send('garbage');
    expect(states.at(-1)).toBe('open');
    expect(events).toHaveLength(1);
  });

  it('shows reconnecting while the browser retries on its own, then resyncs on reopen', () => {
    const { client, states, resync } = make();
    client.start();
    const es = FakeES.all[0]!;
    es.open();
    expect(resync).not.toHaveBeenCalled(); // first open: nothing to resync
    es.failTemporarily();
    expect(states.at(-1)).toBe('reconnecting');
    expect(FakeES.all).toHaveLength(1); // no manual reopen: the browser keeps Last-Event-ID semantics
    es.open();
    expect(states.at(-1)).toBe('open');
    expect(resync).toHaveBeenCalledTimes(1);
  });

  it('reopens with backoff when the browser gives up, and resyncs after the new connection opens', () => {
    const { client, states, resync } = make();
    client.start();
    FakeES.all[0]!.open();
    FakeES.all[0]!.failPermanently();
    expect(states.at(-1)).toBe('reconnecting');
    expect(FakeES.all[0]!.closed).toBe(true);
    vi.advanceTimersByTime(999);
    expect(FakeES.all).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(FakeES.all).toHaveLength(2);
    // second failure waits longer (attempt 2 => 2 s)
    FakeES.all[1]!.failPermanently();
    vi.advanceTimersByTime(1999);
    expect(FakeES.all).toHaveLength(2);
    vi.advanceTimersByTime(1);
    expect(FakeES.all).toHaveLength(3);
    FakeES.all[2]!.open();
    expect(states.at(-1)).toBe('open');
    expect(resync).toHaveBeenCalledTimes(1);
  });

  it('ignores events from a superseded connection and stops cleanly', () => {
    const { client, states, events } = make();
    client.start();
    const old = FakeES.all[0]!;
    old.open();
    old.failPermanently();
    vi.advanceTimersByTime(1000);
    old.send(EVENT);
    expect(events).toHaveLength(0);
    client.stop();
    expect(FakeES.all[1]!.closed).toBe(true);
    expect(states.at(-1)).toBe('closed');
    vi.advanceTimersByTime(60_000);
    expect(FakeES.all).toHaveLength(2); // no reconnect after stop
  });
});

describe('LiveProvider (UI)', () => {
  function Probe({ onReload }: { onReload: () => void }) {
    useLiveReload(onReload, (e) => e.service === 'api');
    return <ConnectionBadge />;
  }

  it('shows the connection state, reloads on matching events and on reconnect', () => {
    const reload = vi.fn();
    render(<LiveProvider enabled EventSourceImpl={ES}><Probe onReload={reload} /></LiveProvider>);
    expect(screen.getByRole('status')).toHaveTextContent('Live: connecting…');
    const es = FakeES.all[0]!;
    act(() => es.open());
    expect(screen.getByRole('status')).toHaveTextContent('Live: connected');

    act(() => { es.send({ ...EVENT, service: 'worker' }); vi.advanceTimersByTime(1000); });
    expect(reload).not.toHaveBeenCalled();
    act(() => { es.send(EVENT); vi.advanceTimersByTime(1000); });
    expect(reload).toHaveBeenCalledTimes(1);

    act(() => es.failPermanently());
    expect(screen.getByRole('status')).toHaveTextContent('Live: reconnecting…');
    act(() => vi.advanceTimersByTime(1000));
    act(() => FakeES.all[1]!.open());
    expect(screen.getByRole('status')).toHaveTextContent('Live: connected');
    act(() => vi.advanceTimersByTime(10));
    expect(reload).toHaveBeenCalledTimes(2); // resync refetch after the reconnect
  });

  it('is offline and opens no connection when disabled', () => {
    render(<LiveProvider enabled={false} EventSourceImpl={ES}><ConnectionBadge /></LiveProvider>);
    expect(screen.getByRole('status')).toHaveTextContent('Live: offline');
    expect(FakeES.all).toHaveLength(0);
  });
});
