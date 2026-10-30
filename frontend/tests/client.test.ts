import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError, describeError, newIdempotencyKey, onUnauthorized } from '@/api/client';
import { createMock } from '../mock/router.mjs';
import { installFetch, json } from './helpers';

afterEach(() => vi.unstubAllGlobals());

describe('api client', () => {
  it('generates Idempotency-Keys that satisfy the contract pattern and are unique', () => {
    const keys = new Set(Array.from({ length: 50 }, newIdempotencyKey));
    expect(keys.size).toBe(50);
    for (const k of keys) expect(k).toMatch(/^[A-Za-z0-9_-]{8,64}$/);
  });

  it('sends credentials: include on reads and writes, and a key on every POST', async () => {
    const { calls } = installFetch();
    await api.listServices();
    await api.rediagnose('INC-0001');
    await api.logout();
    expect(calls.every((c) => c.credentials === 'include')).toBe(true);
    expect(calls[0]!.headers['idempotency-key']).toBeUndefined();
    expect(calls[1]!.headers['idempotency-key']).toMatch(/^[A-Za-z0-9_-]{8,64}$/);
    expect(calls[2]!.headers['idempotency-key']).toMatch(/^[A-Za-z0-9_-]{8,64}$/);
  });

  it('percent-encodes path segments', async () => {
    const { calls } = installFetch();
    await expect(api.getIncident('INC-0001/../../x')).rejects.toBeInstanceOf(ApiError);
    expect(calls[0]!.url).toContain('INC-0001%2F..%2F..%2Fx');
  });

  it('maps statuses to safe messages and never exposes the server message', async () => {
    const hostile = '<script>alert(1)</script> at /srv/app/db.py line 9: password=hunter2';
    for (const [status, kind] of [[401, 'unauthenticated'], [403, 'forbidden'], [404, 'not_found'], [409, 'conflict'], [422, 'invalid'], [429, 'rate_limited'], [503, 'unavailable'], [500, 'unknown']] as const) {
      installFetch(createMock(), () => json(status, { code: 'x_code', message: hostile }));
      const err = await api.getStatus().catch((e: unknown) => e);
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).kind).toBe(kind);
      expect(describeError(err)).not.toMatch(/script|hunter2|db\.py/);
    }
  });

  it('keeps only well-formed codes and rule ids', async () => {
    installFetch(createMock(), () => json(403, { code: 'Bad Code <b>', message: 'm', rule_ids: ['I-01', 'x y', '<i>', 'C-DEFAULT', 5] }));
    const err = (await api.getStatus().catch((e: unknown) => e)) as ApiError;
    expect(err.code).toBeUndefined();
    expect(err.ruleIds).toEqual(['I-01', 'C-DEFAULT']);
  });

  it('reports network failures without details', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('connect ECONNREFUSED 10.0.0.5:8080'); }));
    const err = (await api.getStatus().catch((e: unknown) => e)) as ApiError;
    expect(err.kind).toBe('network');
    expect(describeError(err)).not.toContain('10.0.0.5');
  });

  it('notifies on 401 (except for the login call itself)', async () => {
    installFetch(createMock(), () => json(401, { code: 'unauthenticated', message: 'x' }));
    const fn = vi.fn();
    const off = onUnauthorized(fn);
    await api.listServices().catch(() => undefined);
    expect(fn).toHaveBeenCalledTimes(1);
    await api.login('whatever-token').catch(() => undefined);
    expect(fn).toHaveBeenCalledTimes(1);
    off();
  });

  it('describeError is safe for arbitrary thrown values', () => {
    expect(describeError('<script>')).not.toContain('<script>');
    expect(describeError(undefined)).toMatch(/Unexpected/);
  });
});
