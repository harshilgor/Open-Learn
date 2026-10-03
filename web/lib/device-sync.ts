/** A durable transport queue. Acceptance is not evidence of understanding. */
import { request } from './api';

type PendingEvent = { id: string; device_sequence: number; occurred_at: string; kind: 'client.checkpoint'; payload: Record<string, unknown> };
type Queue = { sequence: number; pending: PendingEvent[]; cursor: number };
const key = (owner: string, device: string) => `openlearn-sync-v1:${owner}:${device}`;

export function syncState(owner: string, device: string): Queue {
  const value = localStorage.getItem(key(owner, device));
  return value ? JSON.parse(value) as Queue : { sequence: 0, pending: [], cursor: 0 };
}

export function enqueueCheckpoint(owner: string, device: string, payload: Record<string, unknown>) {
  const state = syncState(owner, device);
  state.sequence += 1;
  state.pending.push({ id: crypto.randomUUID(), device_sequence: state.sequence, occurred_at: new Date().toISOString(), kind: 'client.checkpoint', payload });
  // A storage failure is surfaced, never represented as a queued observation.
  localStorage.setItem(key(owner, device), JSON.stringify(state));
  return state.pending.length;
}

export async function flushDevice(owner: string, device: string) {
  // Serialize tabs sharing one device grant to avoid duplicate sequence allocation.
  const flush = async () => {
    const state = syncState(owner, device);
    if (state.pending.length) {
      const result = await request<{ acknowledged: { id: string; acceptedOrder: number }[]; deviceSequence: number }>('/v1/account/sync', { method: 'POST', body: JSON.stringify({ events: state.pending.slice(0, 100) }) });
      const accepted = new Set(result.acknowledged.map(event => event.id));
      const latest = syncState(owner, device);
      latest.pending = latest.pending.filter(event => !accepted.has(event.id));
      latest.sequence = Math.max(latest.sequence, result.deviceSequence);
      localStorage.setItem(key(owner, device), JSON.stringify(latest));
    }
    return syncState(owner, device).pending.length;
  };
  return navigator.locks ? navigator.locks.request(`openlearn-sync:${device}`, flush) : flush();
}
