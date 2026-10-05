/** Per-account pending writes. No credentials or claimed server results are stored. */
export type PendingCommand = { id: string; ownerId: string; url: string; method: string; body: string; commandKey?: string; createdAt: number; status: 'pending' | 'conflict' };
export const PENDING_CHANGED = 'openlearn-pending-commands';
const storageKey = (owner: string) => `openlearn-pending-v1:${owner}`;
export function pendingCommands(owner: string): PendingCommand[] {
  return JSON.parse(localStorage.getItem(storageKey(owner)) || '[]') as PendingCommand[];
}
function save(owner: string, commands: PendingCommand[]) {
  localStorage.setItem(storageKey(owner), JSON.stringify(commands));
  window.dispatchEvent(new Event(PENDING_CHANGED));
}
export function rememberCommand(owner: string, url: string, init: RequestInit): PendingCommand | undefined {
  const method = (init.method || 'GET').toUpperCase();
  const path = new URL(url, window.location.origin).pathname;
  const isNote = method === 'PATCH' && /\/workspace-notes\/[^/]+$/.test(path);
  const isQuiz = method === 'POST' && /\/quizzes\/[^/]+\/(answer|answers|hint|pause|resume)$/.test(path);
  const isFlashcard = method === 'POST' && /\/flashcard-(decks|review-sessions)\/[^/]+\/(commands|publish)$/.test(path);
  if ((!isNote && !isQuiz && !isFlashcard) || typeof init.body !== 'string') return;
  const commands = pendingCommands(owner);
  const commandKey = new Headers(init.headers).get('Idempotency-Key') || undefined;
  const existing = commands.find(item => item.url === url && item.body === init.body && item.method === method);
  if (existing) return existing;
  const item: PendingCommand = { id: crypto.randomUUID(), ownerId: owner, url, method, body: init.body, commandKey, createdAt: Date.now(), status: 'pending' };
  save(owner, [...commands, item]);
  return item;
}
export function forgetCommand(owner: string, id: string) { save(owner, pendingCommands(owner).filter(item => item.id !== id)); }
export function markConflict(owner: string, id: string) { save(owner, pendingCommands(owner).map(item => item.id === id ? { ...item, status: 'conflict' } : item)); }
