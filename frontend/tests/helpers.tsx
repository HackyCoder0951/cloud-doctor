import { vi } from 'vitest';
import { createMock, type Mock, type MockRequest, type MockResponse } from '../mock/router.mjs';

export interface Call { method: string; url: string; path: string; headers: Record<string, string>; body: unknown; credentials: RequestCredentials | undefined }

/** Routes fetch() into the mock router (the same data the mock HTTP server serves). */
export function installFetch(mock: Mock = createMock(), override?: (req: MockRequest) => MockResponse | undefined) {
  const calls: Call[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost');
    const headers: Record<string, string> = {};
    new Headers(init?.headers).forEach((v, k) => { headers[k.toLowerCase()] = v; });
    const method = (init?.method ?? 'GET').toUpperCase();
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined;
    const path = url.pathname.replace(/^\/api\/v1/, '');
    calls.push({ method, url: String(input), path, headers, body, credentials: init?.credentials });
    const req: MockRequest = { method, path, query: url.searchParams, headers, body };
    const res = override?.(req) ?? mock.handle(req);
    if (res.text !== undefined) return new Response(res.text, { status: res.status, headers: { 'Content-Type': res.contentType ?? 'text/plain' } });
    if (res.body === null || res.body === undefined) return new Response(null, { status: res.status === 200 ? 204 : res.status });
    return new Response(JSON.stringify(res.body), { status: res.status, headers: { 'Content-Type': 'application/json' } });
  });
  vi.stubGlobal('fetch', fn);
  return { mock, calls, fn };
}

export const json = (status: number, body: unknown): MockResponse => ({ status, body });
