'use client';
import { useCallback, useEffect, useRef, useState } from 'react';

export interface ApiState<T> {
  data: T | undefined;
  error: unknown;
  loading: boolean;
  reload: () => void;
}

/** Client-side data loading (static export: nothing is fetched at build time). */
export function useApi<T>(fn: () => Promise<T>, deps: readonly unknown[]): ApiState<T> {
  const [state, setState] = useState<{ data: T | undefined; error: unknown; loading: boolean }>({ data: undefined, error: undefined, loading: true });
  const [tick, setTick] = useState(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    let cancelled = false;
    setState((s) => ({ ...s, loading: true }));
    fnRef.current().then(
      (data) => { if (!cancelled) setState({ data, error: undefined, loading: false }); },
      (error: unknown) => { if (!cancelled) setState((s) => ({ data: s.data, error, loading: false })); },
    );
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { ...state, reload };
}
