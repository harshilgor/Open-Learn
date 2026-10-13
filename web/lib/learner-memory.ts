import { request } from './api';

/** Opens Settings → Memory, where remembered facts are reviewed. */
export const MEMORY_SETTINGS_OPEN_EVENT = 'openlearn:open-memory-settings';
export const MEMORY_NOTICE_KEY = 'openlearn-memory-notice-v1';

export type MemoryBasis = { type: string; sessionId?: string; turnIndex?: number; quote?: string; sourceId?: string; revision?: number };
export type MemoryFact = {
  id: string; kind: string; statement: string; courseId: string | null; origin: string; status: string;
  learnedAt: number; revision: number;
  eventDate?: string | null; sensitive?: boolean; sensitiveEnabled?: boolean; needsReview?: boolean;
  confirmedAt?: number | null; basis?: MemoryBasis[];
};
export type MemorySettings = { learningEnabled: boolean; revision: number; updatedAt: number | null; extraction: 'on' | 'off' };
export type PastedRange = { start: number; end: number };

/**
 * Character ranges of pasted snippets that are still present in the final
 * message. Pasted text never supports a remembered fact about the learner.
 */
export function pastedRangesFor(message: string, snippets: readonly string[]): PastedRange[] {
  const ranges: PastedRange[] = [];
  for (const snippet of new Set(snippets.filter(item => item.trim()))) {
    let from = 0;
    while (ranges.length < 50) {
      const start = message.indexOf(snippet, from);
      if (start < 0) break;
      ranges.push({ start, end: start + snippet.length });
      from = start + snippet.length;
    }
  }
  return ranges.sort((a, b) => a.start - b.start);
}

/** The learner's IANA timezone, so "Friday" resolves to their Friday. */
export function clientTimezone(): string | undefined {
  try {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return zone && /^[A-Za-z0-9_+\-/]{1,64}$/.test(zone) ? zone : undefined;
  } catch {
    return undefined;
  }
}

export async function turnMemories(generationId: string): Promise<MemoryFact[]> {
  const data = await request<{ items: MemoryFact[] }>(`/v1/memory/facts?generation_id=${encodeURIComponent(generationId)}`);
  return data.items;
}

export async function undoMemory(factId: string): Promise<void> {
  await request(`/v1/memory/facts/${encodeURIComponent(factId)}?undo=true`, { method: 'DELETE' });
}

export function memorySettings(): Promise<MemorySettings> {
  return request<MemorySettings>('/v1/memory/settings');
}

// --- Memory page (spec §10, Phase F2) -----------------------------------------

export type MemoryEpisode = { id: string; sessionId: string; courseId: string | null; periodStart: number; periodEnd: number; summary: string; topics: string[] };
export type MemoryChange = { at: number; source: string; summary: string };
export type MemoryProfile = { source: 'stored' | 'preview'; text: string; items: MemoryFact[] };
export type FactInput = { statement: string; kind: string; courseId: string | null; eventDate: string | null };
export type ForgetPreview = { facts: number; episodes: number; confirmation: string };

/** Fact kinds in page order, with learner-facing group names. */
export const MEMORY_KINDS: { kind: string; label: string }[] = [
  { kind: 'deadline', label: 'Deadlines' }, { kind: 'goal', label: 'Goals' }, { kind: 'constraint', label: 'Constraints' },
  { kind: 'preference', label: 'Preferences' }, { kind: 'background', label: 'Background' }, { kind: 'interest', label: 'Interests' },
  { kind: 'strategy_feedback', label: 'What helps you learn' }, { kind: 'note_to_self', label: 'Notes to self' },
];

const fact = (id: string) => `/v1/memory/facts/${encodeURIComponent(id)}`;
const json = (method: string, body: unknown) => ({ method, body: JSON.stringify(body) });

export const memoryApi = {
  facts: (status: 'active' | 'tentative' | 'archived') => request<{ items: MemoryFact[] }>(`/v1/memory/facts?status=${status}`).then(data => data.items),
  history: (id: string) => request<{ items: MemoryFact[] }>(`${fact(id)}/history`).then(data => data.items),
  profile: () => request<MemoryProfile>('/v1/memory/profile'),
  changes: () => request<{ items: MemoryChange[] }>('/v1/memory/changes').then(data => data.items),
  episodes: () => request<{ items: MemoryEpisode[] }>('/v1/memory/episodes').then(data => data.items),
  settings: memorySettings,
  add: (input: FactInput) => request<MemoryFact>('/v1/memory/facts', json('POST', input)),
  edit: (item: MemoryFact, input: FactInput) => request<MemoryFact>(fact(item.id), json('PATCH', { ...input, expectedRevision: item.revision })),
  confirm: (item: MemoryFact) => request<MemoryFact>(`${fact(item.id)}/confirm`, json('POST', { expectedRevision: item.revision })),
  setSensitive: (item: MemoryFact, enabled: boolean) => request<MemoryFact>(`${fact(item.id)}/sensitive`, json('PUT', { enabled, expectedRevision: item.revision })),
  forget: (item: MemoryFact) => request(fact(item.id), { method: 'DELETE' }),
  deleteEpisode: (id: string) => request(`/v1/memory/episodes/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  setLearning: (settings: MemorySettings, learningEnabled: boolean) =>
    request<MemorySettings>('/v1/memory/settings', json('PUT', { learningEnabled, expectedRevision: settings.revision })),
  forgetPreview: () => request<ForgetPreview>('/v1/memory/forget-all'),
  forgetAll: (confirmation: string) => request<{ facts: number; episodes: number }>('/v1/memory/forget-all', json('POST', { confirmation })),
};
