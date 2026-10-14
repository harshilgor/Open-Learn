/** Small, framework-free helpers behind the note editor's writing affordances. */

export type NoteTemplate = { id: string; label: string; description: string; title: string; body: string };

/** Starting structures offered on a blank note. Bodies are the editor's Markdown. */
export const NOTE_TEMPLATES: NoteTemplate[] = [
  { id: 'lecture', label: 'Lecture notes', description: 'Key ideas, details and open questions', title: 'Lecture notes', body: '## Key ideas\n\n- \n\n## Details\n\n- \n\n## Questions to follow up\n\n- [ ] ' },
  { id: 'cornell', label: 'Cornell', description: 'Cues, notes and a summary', title: 'Cornell notes', body: '## Cues\n\n- \n\n## Notes\n\n- \n\n## Summary\n\nIn my own words: ' },
  { id: 'summary', label: 'Summary', description: 'One sentence, main points, examples', title: 'Summary', body: '## In one sentence\n\n\n\n## Main points\n\n1. \n\n## Examples\n\n- \n\n## Still unsure about\n\n- ' },
  { id: 'problems', label: 'Problem set', description: 'Given, find, approach, answer', title: 'Problem set', body: '## Problem 1\n\n**Given:** \n\n**Find:** \n\n**Approach:** \n\n**Answer:** \n\n## Problem 2\n\n**Given:** \n\n**Find:** \n\n**Approach:** \n\n**Answer:** ' },
];

export type SlashCommandId = 'heading' | 'subheading' | 'bullet' | 'numbered' | 'checklist' | 'quote' | 'divider' | 'image' | 'visual' | 'quiz';
export type SlashCommand = { id: SlashCommandId; label: string; hint: string; keywords: string };

export const SLASH_COMMANDS: SlashCommand[] = [
  { id: 'heading', label: 'Heading', hint: 'Section heading', keywords: 'h2 title section' },
  { id: 'subheading', label: 'Subheading', hint: 'Smaller heading', keywords: 'h3' },
  { id: 'bullet', label: 'Bulleted list', hint: 'Type - then space', keywords: 'ul list' },
  { id: 'numbered', label: 'Numbered list', hint: 'Type 1. then space', keywords: 'ol list' },
  { id: 'checklist', label: 'Checklist', hint: 'Type [] then space', keywords: 'todo task check' },
  { id: 'quote', label: 'Quote', hint: 'Type > then space', keywords: 'blockquote callout' },
  { id: 'divider', label: 'Divider', hint: 'Separate sections', keywords: 'hr line rule' },
  { id: 'image', label: 'Image', hint: 'Upload a picture', keywords: 'picture photo upload' },
  { id: 'visual', label: 'Visual', hint: 'Ask Buddy to draw this note', keywords: 'diagram chart graph canvas draw' },
  { id: 'quiz', label: 'Quiz me', hint: 'Practice this note', keywords: 'practice test question' },
];

export function matchSlashCommands(query: string): SlashCommand[] {
  const value = query.trim().toLowerCase();
  if (!value) return SLASH_COMMANDS;
  return SLASH_COMMANDS.filter(command => command.label.toLowerCase().includes(value) || command.keywords.includes(value));
}

/** The text typed after a slash at the start of a block or after a space, if any. */
export function slashQuery(textBeforeCaret: string): string | null {
  const match = textBeforeCaret.replace(/ /g, ' ').match(/(?:^|\s)\/([A-Za-z]{0,20})$/);
  return match ? match[1] : null;
}

export type MarkdownShortcut = 'heading' | 'subheading' | 'bullet' | 'numbered' | 'checklist' | 'quote';

/** A Markdown block marker typed at the start of a line, converted when space is pressed. */
export function markdownShortcut(textBeforeCaret: string): MarkdownShortcut | null {
  const marker = textBeforeCaret.replace(/ /g, ' ');
  if (marker === '#') return 'heading';
  if (marker === '##' || marker === '###') return 'subheading';
  if (marker === '-' || marker === '*') return 'bullet';
  if (marker === '1.') return 'numbered';
  if (marker === '[]' || marker === '[ ]') return 'checklist';
  if (marker === '>') return 'quote';
  return null;
}

/** "Just now", "5m ago", "3h ago", "Yesterday", a weekday within a week, then a date. */
export function relativeTime(value: string, now = Date.now()): string {
  const time = new Date(value).getTime();
  if (!Number.isFinite(time)) return '';
  const seconds = Math.max(0, (now - time) / 1000);
  if (seconds < 60) return 'Just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  const date = new Date(time), today = new Date(now);
  const days = Math.round((new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime() - new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()) / 86400000);
  if (days === 0) return `${Math.floor(seconds / 3600)}h ago`;
  if (days === 1) return 'Yesterday';
  if (days < 7) return new Intl.DateTimeFormat(undefined, { weekday: 'long' }).format(date);
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', ...(date.getFullYear() !== today.getFullYear() ? { year: 'numeric' } : {}) }).format(date);
}

/** Words of prose, ignoring embedded images and visual blocks. */
export function noteWordCount(body: string): number {
  return body.replace(/!\[[^\]]*\]\(data:[^)]+\)/g, '').replace(/```(?:visualization-ref|visual-artifact)\n[^\n]*\n```/g, '').trim().split(/\s+/).filter(Boolean).length;
}

export type NoteFilter = 'all' | 'personal' | 'lessons' | 'classes';
export const NOTE_FILTERS: { id: NoteFilter; label: string }[] = [
  { id: 'all', label: 'All' }, { id: 'personal', label: 'Mine' }, { id: 'lessons', label: 'Lessons' }, { id: 'classes', label: 'Classes' },
];

export function matchesNoteFilter(note: { noteType: string; frontmatter: Record<string, unknown> }, filter: NoteFilter): boolean {
  const fromClass = note.noteType === 'recording' || typeof note.frontmatter.class_recording_id === 'string' || typeof note.frontmatter.lecture_recording_id === 'string' || note.frontmatter.source === 'in_class';
  if (filter === 'lessons') return note.noteType === 'lesson';
  if (filter === 'classes') return fromClass;
  if (filter === 'personal') return note.noteType !== 'lesson' && !fromClass;
  return true;
}
