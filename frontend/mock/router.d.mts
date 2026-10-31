export interface MockResponse { status: number; body?: unknown; text?: string; contentType?: string }
export interface MockRequest { method: string; path: string; query?: URLSearchParams; headers?: Record<string, string>; body?: unknown }
export interface MockEvent { id: number; payload: Record<string, unknown> }
export interface Mock {
  handle(req: MockRequest): MockResponse;
  emit(type: string, fields?: Record<string, unknown>): MockEvent;
  subscribe(fn: (e: MockEvent) => void): () => void;
  eventsAfter(id: number): MockEvent[];
  setStatus(state: 'ok' | 'degraded' | 'fail_closed'): void;
  completeApproved(incident: string, plan: string): void;
  incidents: Record<string, any>;
  status: any;
}
export function createMock(opts?: { now?: () => number }): Mock;
export function renderMarkdown(report: unknown): string;
