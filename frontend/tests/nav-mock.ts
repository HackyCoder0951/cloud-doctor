import { vi } from 'vitest';

export const nav = { replace: vi.fn(), push: vi.fn(), params: new URLSearchParams(), path: '/' };

export function setupNav(path = '/', params = '') {
  nav.replace = vi.fn();
  nav.push = vi.fn();
  nav.params = new URLSearchParams(params);
  nav.path = path;
}
