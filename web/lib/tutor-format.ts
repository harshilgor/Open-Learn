export type ConceptLink = { term: string; definition?: string };
export type Exercise = { id: string; type: 'numeric' | 'short_text'; prompt: string; answer: string; explanation: string; hint?: string; tolerance?: number };
export type ExerciseParse = { status: 'valid'; exercise: Exercise } | { status: 'partial' | 'invalid' };

export function parseConceptLink(raw: string): ConceptLink | null {
  const match = /^\[\[([^\[\]|\n]{1,80})(?:\|([^\[\]|\n]{1,180}))?\]\]$/.exec(raw);
  if (!match) return null;
  const term = match[1].trim();
  const definition = match[2]?.trim();
  if (!term || (match[2] !== undefined && !definition) || (definition && definition.split(/\s+/).length > 15)) return null;
  return { term, ...(definition ? { definition } : {}) };
}

export function parseExerciseJson(raw: string, complete = true): ExerciseParse {
  let value: unknown;
  try { value = JSON.parse(raw); } catch { return { status: complete ? 'invalid' : 'partial' }; }
  if (!value || typeof value !== 'object' || Array.isArray(value)) return { status: 'invalid' };
  const item = value as Record<string, unknown>;
  if (typeof item.id !== 'string' || !/^[a-zA-Z0-9_-]{1,64}$/.test(item.id) || !['numeric', 'short_text'].includes(String(item.type)) || typeof item.prompt !== 'string' || !item.prompt.trim() || typeof item.explanation !== 'string' || !item.explanation.trim() || !['string', 'number'].includes(typeof item.answer) || !String(item.answer).trim()) return { status: 'invalid' };
  if (item.hint !== undefined && typeof item.hint !== 'string') return { status: 'invalid' };
  if (item.tolerance !== undefined && (typeof item.tolerance !== 'number' || !Number.isFinite(item.tolerance) || item.tolerance < 0)) return { status: 'invalid' };
  if (item.type === 'numeric' && !Number.isFinite(Number(item.answer))) return { status: 'invalid' };
  return { status: 'valid', exercise: { id: item.id, type: item.type as Exercise['type'], prompt: item.prompt.trim(), answer: String(item.answer).trim(), explanation: item.explanation.trim(), ...(typeof item.hint === 'string' ? { hint: item.hint.trim() } : {}), ...(typeof item.tolerance === 'number' ? { tolerance: item.tolerance } : {}) } };
}

export function normalizeShortAnswer(value: string) {
  return value.normalize('NFKC').toLocaleLowerCase().replace(/[^\p{L}\p{N}\s]/gu, ' ').replace(/\s+/g, ' ').trim();
}

export function checkExerciseAnswer(exercise: Exercise, answer: string): boolean {
  if (exercise.type === 'short_text') return normalizeShortAnswer(answer) === normalizeShortAnswer(exercise.answer);
  const actual = Number(answer.trim());
  const expected = Number(exercise.answer);
  if (!answer.trim() || !Number.isFinite(actual) || !Number.isFinite(expected)) return false;
  return Math.abs(actual - expected) <= (exercise.tolerance ?? Math.max(1e-9, Math.abs(expected) * 1e-9));
}

export type TutorPart = { kind: 'markdown'; body: string } | { kind: 'exercise'; exercise: Exercise } | { kind: 'pending_exercise' | 'invalid_exercise' };

export function splitTutorContent(body: string): TutorPart[] {
  const parts: TutorPart[] = [];
  const fence = /^```exercise\s*\n([\s\S]*?)\n```[ \t]*(?:\n|$)/gm;
  const seen = new Set<string>();
  let cursor = 0;
  for (const match of body.matchAll(fence)) {
    const start = match.index ?? 0;
    if (start > cursor) parts.push({ kind: 'markdown', body: body.slice(cursor, start) });
    const parsed = parseExerciseJson(match[1]);
    if (parsed.status === 'valid' && !seen.has(parsed.exercise.id)) { parts.push({ kind: 'exercise', exercise: parsed.exercise }); seen.add(parsed.exercise.id); }
    else parts.push({ kind: 'invalid_exercise' });
    cursor = start + match[0].length;
  }
  if (cursor < body.length) {
    const tail = body.slice(cursor);
    const incomplete = /(?:^|\n)```exercise[ \t]*\n/.exec(tail);
    if (incomplete) {
      const start = incomplete.index + (tail[incomplete.index] === '\n' ? 1 : 0);
      if (start > 0) parts.push({ kind: 'markdown', body: tail.slice(0, start) });
      parts.push({ kind: 'pending_exercise' });
    } else parts.push({ kind: 'markdown', body: tail });
  }
  return parts.length ? parts : [{ kind: 'markdown', body }];
}

export function encodeConceptLinks(markdown: string): string {
  return markdown.split(/(```[\s\S]*?```|`[^`\n]*`)/g).map((part, index) => {
    if (index % 2) return part;
    return part.replace(/\[\[[^\[\]\n]+\]\]/g, raw => {
      const parsed = parseConceptLink(raw);
      return parsed ? `[${parsed.term}](concept:${encodeURIComponent(parsed.term)}${parsed.definition ? `?definition=${encodeURIComponent(parsed.definition)}` : ''})` : raw;
    });
  }).join('');
}
