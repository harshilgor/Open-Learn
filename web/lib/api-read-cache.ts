// Browser-only, bounded cache. Authority snapshots and balances are never retained.
type Entry = { promise: Promise<unknown>; expiresAt: number; settled: boolean };
export class ApiReadCache {
  private entries = new Map<string, Entry>();
  clear() { this.entries.clear(); }
  async read<T>(key: string, load: () => Promise<T>, freshnessMs = 0): Promise<T> {
    const current = this.entries.get(key);
    if (current && (!current.settled || current.expiresAt > Date.now())) {
      return structuredClone(await current.promise) as T;
    }
    this.entries.delete(key);
    // Keep memory bounded even when a user opens many different resources.
    if (this.entries.size >= 100) this.entries.delete(this.entries.keys().next().value!);
    const entry: Entry = { promise: Promise.resolve().then(load), expiresAt: 0, settled: false };
    this.entries.set(key, entry);
    try {
      const value = await entry.promise as T;
      entry.settled = true;
      entry.expiresAt = Date.now() + freshnessMs;
      if (!freshnessMs && this.entries.get(key) === entry) this.entries.delete(key);
      return structuredClone(value);
    } catch (error) {
      if (this.entries.get(key) === entry) this.entries.delete(key);
      throw error;
    }
  }
}

export function readFreshness(path: string): number {
  const route = path.split('?')[0];
  // Only navigation summaries: never session snapshots, jobs, usage, or streaming.
  return route === '/v1/courses' || route === '/v1/buddies' || route === '/v1/buddies/today'
    || /^\/v1\/learners\/[^/]+\/review$/.test(route) ? 15_000 : 0;
}
