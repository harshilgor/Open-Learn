import type { WorkspaceSidebarTab } from '@/components/workspace-sidebar';

export function workspacePath(tab: WorkspaceSidebarTab, sessionId: string | null, courseId: string | null, noteId?: string | null): string {
  const path = tab === 'notes' ? '/notes' : sessionId ? `/s/${encodeURIComponent(sessionId)}` : '/chat';
  const query = new URLSearchParams();
  // An empty value preserves an explicit All courses selection on refresh.
  query.set('course', courseId || '');
  if (tab === 'notes' && noteId) query.set('note', noteId);
  return `${path}${query.size ? `?${query}` : ''}`;
}

export function sidebarTabFromPath(path: string): WorkspaceSidebarTab { return path === '/notes' ? 'notes' : 'home'; }
