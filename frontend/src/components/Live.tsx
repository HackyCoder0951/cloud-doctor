'use client';
import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { API_BASE } from '@/api/client';
import type { StreamEvent } from '@/api/types';
import { StreamClient, type ConnState } from '@/lib/sse';

type Message = StreamEvent | 'resync';
type Listener = (m: Message) => void;
interface LiveValue { state: ConnState; subscribe: (l: Listener) => () => void }

const LiveContext = createContext<LiveValue>({ state: 'closed', subscribe: () => () => undefined });
export const useLive = () => useContext(LiveContext);

export function LiveProvider({ enabled, children, EventSourceImpl }: { enabled: boolean; children: ReactNode; EventSourceImpl?: typeof EventSource }) {
  const [state, setState] = useState<ConnState>('closed');
  const listeners = useRef(new Set<Listener>());

  useEffect(() => {
    if (!enabled) return undefined;
    const client = new StreamClient({
      url: `${API_BASE}/stream`,
      EventSourceImpl,
      onState: setState,
      onEvent: (e) => listeners.current.forEach((l) => l(e)),
      onResync: () => listeners.current.forEach((l) => l('resync')),
    });
    client.start();
    return () => client.stop();
  }, [enabled, EventSourceImpl]);

  const value = useMemo<LiveValue>(() => ({
    state,
    subscribe: (l) => { listeners.current.add(l); return () => { listeners.current.delete(l); }; },
  }), [state]);
  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>;
}

/** Reload data when a matching live event arrives (debounced) and after every reconnect. */
export function useLiveReload(reload: () => void, match?: (e: StreamEvent) => boolean) {
  const { subscribe } = useLive();
  const ref = useRef({ reload, match });
  ref.current = { reload, match };
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const off = subscribe((m) => {
      if (m !== 'resync' && ref.current.match && !ref.current.match(m)) return;
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => ref.current.reload(), m === 'resync' ? 0 : 400);
    });
    return () => { off(); if (timer) clearTimeout(timer); };
  }, [subscribe]);
}
