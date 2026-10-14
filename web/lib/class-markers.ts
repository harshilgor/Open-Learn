/**
 * Typed in-class moments ("Mark moment", "I'm confused", "Key point").
 *
 * The capture controller only persists bare timestamps (class_recording_markers_ms),
 * so the kind of each moment is remembered on this device, keyed by recording.
 */
export type ClassMarkerKind = 'moment' | 'confused' | 'key_point';
export type ClassMarker = { id: string; kind: ClassMarkerKind; atMs: number; approximate?: boolean; createdAt: number };

export const CLASS_MARKERS_CHANGED_EVENT = 'openlearn:class-markers-changed';
const STORAGE_PREFIX = 'openlearn.class-markers:';
const MAX_MARKERS = 200;
const EMPTY: ClassMarker[] = [];
const cache = new Map<string, ClassMarker[]>();

function isMarker(value: unknown): value is ClassMarker {
  if (!value || typeof value !== 'object') return false;
  const item = value as Record<string, unknown>;
  return typeof item.id === 'string' && ['moment', 'confused', 'key_point'].includes(item.kind as string) && typeof item.atMs === 'number' && Number.isFinite(item.atMs) && item.atMs >= 0;
}

function load(recordingId: string): ClassMarker[] {
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + recordingId);
    if (!raw) return EMPTY;
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter(isMarker).sort((a, b) => a.atMs - b.atMs) : EMPTY;
  } catch {
    return EMPTY;
  }
}

/** Stable (cached) list for a recording, suitable for useSyncExternalStore. */
export function readClassMarkers(recordingId: string | null | undefined): ClassMarker[] {
  if (!recordingId || typeof window === 'undefined') return EMPTY;
  const cached = cache.get(recordingId);
  if (cached) return cached;
  const value = load(recordingId);
  cache.set(recordingId, value);
  return value;
}

export function serverClassMarkers(): ClassMarker[] {
  return EMPTY;
}

export function addClassMarker(recordingId: string, kind: ClassMarkerKind, atMs: number, approximate = false): ClassMarker {
  const marker: ClassMarker = { id: crypto.randomUUID(), kind, atMs: Math.max(0, Math.round(atMs)), createdAt: Date.now(), ...(approximate ? { approximate: true } : {}) };
  const next = [...readClassMarkers(recordingId), marker].sort((a, b) => a.atMs - b.atMs).slice(-MAX_MARKERS);
  cache.set(recordingId, next);
  try { localStorage.setItem(STORAGE_PREFIX + recordingId, JSON.stringify(next)); } catch { /* Markers stay in memory for this tab. */ }
  window.dispatchEvent(new CustomEvent(CLASS_MARKERS_CHANGED_EVENT, { detail: { recordingId } }));
  return marker;
}

export function subscribeClassMarkers(onChange: () => void): () => void {
  const storage = (event: StorageEvent) => {
    if (event.key && !event.key.startsWith(STORAGE_PREFIX)) return;
    if (event.key) cache.delete(event.key.slice(STORAGE_PREFIX.length)); else cache.clear();
    onChange();
  };
  window.addEventListener(CLASS_MARKERS_CHANGED_EVENT, onChange);
  window.addEventListener('storage', storage);
  return () => { window.removeEventListener(CLASS_MARKERS_CHANGED_EVENT, onChange); window.removeEventListener('storage', storage); };
}

/** Testing and account-switch helper. */
export function resetClassMarkerCache(): void {
  cache.clear();
}

export function formatClassTime(milliseconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = String(totalSeconds % 60).padStart(2, '0');
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${seconds}` : `${minutes}:${seconds}`;
}
