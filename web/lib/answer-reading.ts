/**
 * Presentation helpers for long assistant answers: inline citation markers
 * and the threshold that decides when answer sections become collapsible.
 * Persisted answers stay plain Markdown; these run at render time only.
 */

/** A cited passage as the chat knows it; `spanId` makes it openable. */
export type CitationSource = {
  spanId?: string;
  versionId?: string;
  title?: string;
  pageIndex?: number;
  pageLabel?: string | null;
};

export type ParsedCitation =
  | { kind: 'span'; spanId: string }
  | { kind: 'alias'; alias: string; origin: 'web' | 'material' };

export const CITATION_SCHEME = 'citation:';
const MARKER = /\[(source|web|cite|material):[ \t]*([^[\]\n]{1,160})\](?!\()/gi;
const ALIAS = /^([WM])(\d{1,3})$/i;
const SPAN_ID = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$/;

function encodeMarkerValue(value: string): string | null {
  const alias = ALIAS.exec(value);
  if (alias) {
    const label = `${alias[1].toUpperCase()}${alias[2]}`;
    return `[${label}](${CITATION_SCHEME}alias/${label})`;
  }
  return SPAN_ID.test(value) ? `[Source](${CITATION_SCHEME}span/${encodeURIComponent(value)})` : null;
}

/**
 * Rewrites model citation markers such as `[web:W1]`, `[material:M2, M3]` or
 * `[source:<spanId>]` into `citation:` links the renderer turns into chips.
 * Code spans and fences are left untouched; unrecognised markers stay as text.
 */
export function encodeCitationMarkers(markdown: string): string {
  return markdown.split(/(```[\s\S]*?```|`[^`\n]*`)/g).map((part, index) => {
    if (index % 2) return part;
    return part.replace(MARKER, (raw, _kind: string, body: string) => {
      const values = body.split(/[,;]/).map(value => value.trim()).filter(Boolean);
      const encoded = values.map(encodeMarkerValue);
      return values.length && encoded.every(Boolean) ? encoded.join(' ') : raw;
    });
  }).join('');
}

export function parseCitationHref(href: string): ParsedCitation | null {
  if (!href.startsWith(CITATION_SCHEME)) return null;
  const [type, ...rest] = href.slice(CITATION_SCHEME.length).split('/');
  const value = rest.join('/');
  if (type === 'span' && value) {
    try { return { kind: 'span', spanId: decodeURIComponent(value) }; } catch { return null; }
  }
  const alias = type === 'alias' ? ALIAS.exec(value) : null;
  return alias ? { kind: 'alias', alias: `${alias[1].toUpperCase()}${alias[2]}`, origin: alias[1].toUpperCase() === 'W' ? 'web' : 'material' } : null;
}

/** "p. 4" from a printed page label or zero-based page index, when known. */
export function citationPage(source: CitationSource): string | null {
  const label = source.pageLabel?.trim();
  if (label) return `p. ${label}`;
  return typeof source.pageIndex === 'number' && source.pageIndex >= 0 ? `p. ${source.pageIndex + 1}` : null;
}

/** Full, human-readable description used for hover/focus titles and labels. */
export function citationDescription(source: CitationSource): string {
  const label = source.pageLabel?.trim();
  const page = label ? `Page ${label}` : typeof source.pageIndex === 'number' && source.pageIndex >= 0 ? `Page ${source.pageIndex + 1}` : '';
  return [source.title?.trim(), page].filter(Boolean).join(' · ') || 'Cited passage';
}

export const COLLAPSE_MIN_WORDS = 450;
export const COLLAPSE_MIN_SECTIONS = 3;

type SectionLike = { heading?: string | null; body: string };

export function answerWordCount(blocks: SectionLike[]): number {
  return blocks.reduce((total, block) => total + `${block.heading || ''} ${block.body}`.split(/\s+/).filter(Boolean).length, 0);
}

/** Long answers (> ~450 words with at least three headed sections) collapse later sections. */
export function shouldCollapseAnswer(blocks: SectionLike[]): boolean {
  const headed = blocks.filter(block => block.heading?.trim()).length;
  return headed >= COLLAPSE_MIN_SECTIONS && answerWordCount(blocks) > COLLAPSE_MIN_WORDS;
}
