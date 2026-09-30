import type { WorkspaceNoteSummary } from './api';

export function noteDisplayTitle(note: WorkspaceNoteSummary, notes: WorkspaceNoteSummary[]): string {
  const matches = notes.filter(item => item.title.trim().toLowerCase() === note.title.trim().toLowerCase());
  if (matches.length < 2) return note.title;
  const date = new Date(String(note.frontmatter.created_at || note.updatedAt)).toLocaleDateString();
  const sameDate = matches.filter(item => new Date(String(item.frontmatter.created_at || item.updatedAt)).toLocaleDateString() === date).sort((a, b) => a.id.localeCompare(b.id));
  return `${note.title} · ${date}${sameDate.length > 1 ? ` · ${sameDate.findIndex(item => item.id === note.id) + 1}` : ''}`;
}
