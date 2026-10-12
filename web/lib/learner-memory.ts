import { request } from './api';

/** Opens Settings → Privacy & data, where remembered facts are reviewed. */
export const MEMORY_SETTINGS_OPEN_EVENT = 'openlearn:open-memory-settings';
export const MEMORY_NOTICE_KEY = 'openlearn-memory-notice-v1';

export type MemoryFact = {
  id: string; kind: string; statement: string; courseId: string | null; origin: string; status: string;
  learnedAt: number; revision: number;
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
