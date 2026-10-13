/** Short-lived authenticated snapshots. No storage, credentials or URL broadcasts. */
type Snapshot = { value: unknown; expires: number; revision: number };
const snapshots = new Map<string, Snapshot>();
let revision = 0;
let invalidatedAt = 0;
let channel: BroadcastChannel | undefined;
function bus() {
  if (typeof window === 'undefined' || typeof BroadcastChannel === 'undefined') return undefined;
  if (!channel) {
    try { channel = new BroadcastChannel('openlearn-read-snapshots-v1'); }
    catch { return undefined; }
    channel.onmessage = event => {
      const message = event.data;
      if (message?.type === 'invalidate') {
        revision++; invalidatedAt = Date.now(); snapshots.clear();
        window.dispatchEvent(new Event('openlearn-read-invalidated'));
        return;
      }
      if (message?.type !== 'snapshot' || typeof message.key !== 'string' || !/^[a-f0-9]{64}$/.test(message.key)) return;
      if (typeof message.expires !== 'number' || message.expires <= Date.now() || message.expires > Date.now() + 1000) return;
      if (typeof message.startedAt !== 'number' || message.startedAt <= invalidatedAt) return;
      if (snapshots.size >= 64) snapshots.delete(snapshots.keys().next().value!);
      snapshots.set(message.key, { value: message.value, expires: message.expires, revision });
    };
  }
  return channel;
}
export function invalidateCrossTabReads(broadcast = true) {
  revision++; invalidatedAt = Date.now(); snapshots.clear();
  if (broadcast) bus()?.postMessage({ type: 'invalidate' });
}
export async function crossTabRead<T>(identityKey: string, load: () => Promise<T>, freshnessMs: number,
  stillValid: () => boolean = () => true): Promise<T> {
  // Authority reads, streams, mutations and abortable requests never enter here.
  if (!freshnessMs || typeof navigator === 'undefined' || !navigator.locks || !bus() || !crypto.subtle) return load();
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(identityKey));
  const key = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
  const epoch = revision;
  const waiting = new AbortController();
  const deadline = window.setTimeout(() => waiting.abort(), 150);
  let acquired = false;
  try { return await navigator.locks.request(`openlearn-read:${key}`, { signal: waiting.signal }, async () => {
    acquired = true;
    window.clearTimeout(deadline);
    // Broadcast delivery may lag lock acquisition by one browser task.
    await new Promise(resolve => setTimeout(resolve, 0));
    const cached = snapshots.get(key);
    if (stillValid() && revision === epoch && cached?.revision === revision && cached.expires > Date.now()) return structuredClone(cached.value) as T;
    const startedAt = Date.now();
    const value = await load();
    if (stillValid() && revision === epoch) {
      const expires = Date.now() + Math.min(freshnessMs, 500);
      // Bound message size. Large histories are loaded separately in each tab.
      try {
        if ((JSON.stringify(value)?.length ?? Infinity) < 256_000) {
          if (snapshots.size >= 64) snapshots.delete(snapshots.keys().next().value!);
          snapshots.set(key, { value: structuredClone(value), expires, revision });
          bus()?.postMessage({ type: 'snapshot', key, expires, startedAt, value });
        }
      } catch { /* Optional coordination must not turn a successful GET into an error. */ }
    }
    return value;
  }); } catch (cause) {
    // A suspended peer must not leave another tab waiting indefinitely.
    // Once our callback runs, preserve its real loader error without retrying it.
    if (!acquired) return load();
    throw cause;
  } finally { window.clearTimeout(deadline); }
}
