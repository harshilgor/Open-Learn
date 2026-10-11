import { afterEach, describe, expect, it, vi } from 'vitest';
import { GET } from '../app/api/release/route';

afterEach(() => vi.unstubAllEnvs());

describe('immutable release metadata', () => {
  it('uses the explicit release commit over inherited Vercel Git metadata', async () => {
    vi.stubEnv('OPENLEARN_RELEASE_SHA', 'a'.repeat(40));
    vi.stubEnv('VERCEL_GIT_COMMIT_SHA', 'b'.repeat(40));
    const metadata = await GET(new Request('https://frontend.example/api/release')).json();
    expect(metadata.commit).toBe('a'.repeat(40));
  });

  it('retains Git metadata for deployments without an explicit release SHA', async () => {
    vi.stubEnv('OPENLEARN_RELEASE_SHA', '');
    vi.stubEnv('VERCEL_GIT_COMMIT_SHA', 'b'.repeat(40));
    const response = GET(new Request('https://frontend.example/api/release'));
    expect((await response.json()).commit).toBe('b'.repeat(40));
    expect(response.headers.get('cache-control')).toBe('no-store');
  });
});
