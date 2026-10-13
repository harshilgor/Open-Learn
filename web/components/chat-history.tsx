"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Ellipsis, Plus } from 'lucide-react';
import { learningApi, LearningApiError, type ChatSessionSummary, type CourseSummary } from '@/lib/api';
import styles from './chat-history.module.css';
import { useBuddies } from './buddies';

type Group = 'Today' | 'Yesterday' | 'Previous 7 days' | 'Older';

function groupFor(iso: string, now: Date): Group {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return 'Older';
  const startOf = (value: Date) => new Date(value.getFullYear(), value.getMonth(), value.getDate());
  const days = Math.round((startOf(now).getTime() - startOf(date).getTime()) / 86400000);
  if (days <= 0) return 'Today';
  if (days === 1) return 'Yesterday';
  if (days <= 7) return 'Previous 7 days';
  return 'Older';
}

const GROUP_ORDER: Group[] = ['Today', 'Yesterday', 'Previous 7 days', 'Older'];

function relativeTime(iso: string, now: Date) {
  const minutes = Math.max(0, Math.floor((now.getTime() - new Date(iso).getTime()) / 60000));
  if (!Number.isFinite(minutes)) return '';
  if (minutes < 1) return 'Just now';
  if (minutes < 60) return `${minutes}m ago`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)}h ago`;
  if (minutes < 10080) return `${Math.floor(minutes / 1440)}d ago`;
  return new Date(iso).toLocaleDateString();
}

export function ChatHistory({ activeSessionId, refreshKey, onOpen, courses = [], courseFilter = null, fixedBuddyId }: {
  activeSessionId: string | null;
  refreshKey: number;
  onOpen: (sessionId: string | null) => void;
  courses?: CourseSummary[];
  courseFilter?: string | null;
  fixedBuddyId?: string;
}) {
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [buddyFilter, setBuddyFilter] = useState('');
  const [search, setSearch] = useState('');
  const [pinned, setPinned] = useState<string[]>(()=>{try{const value:unknown=JSON.parse(localStorage.getItem('openlearn-pinned-chats-v1')||'[]');return Array.isArray(value)?value.filter((id):id is string=>typeof id==='string'):[];}catch{return [];}});
  function togglePin(id:string){const next=pinned.includes(id)?pinned.filter(value=>value!==id):[...pinned,id];setPinned(next);try{localStorage.setItem('openlearn-pinned-chats-v1',JSON.stringify(next));}catch{/* Optional local preference. */}}
  const buddies=useBuddies();
  const refreshBuddies=buddies.refresh;
  const [total,setTotal]=useState(0),[loadingMore,setLoadingMore]=useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [errorDetail, setErrorDetail] = useState('');

  function friendlyError(cause: unknown): { message: string; detail: string } {
    const detail = cause instanceof Error ? cause.message : 'Unknown error.';
    if (cause instanceof LearningApiError && (cause.status === 404 || cause.status === 405)) {
      return { message: 'Chat history needs a newer tutor service.', detail: 'Please retry. Your saved conversations are retained.' };
    }
    if ((cause instanceof LearningApiError && cause.status >= 500) || detail.startsWith('Cannot connect to the tutor service')) {
      return { message: 'Could not reach the tutor service.', detail: 'Please retry. Your chats stay saved on the server.' };
    }
    return { message: 'Could not load conversations.', detail: 'Please retry. Your chats stay saved on the server.' };
  }
  const [menuId, setMenuId] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const renameInput = useRef<HTMLInputElement | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    setErrorDetail('');
    try {
      const result = await learningApi.listChatSessions({ limit: 100 });
      setSessions(result.sessions);
      setTotal(result.total);
      void refreshBuddies().catch(() => {});
    } catch (cause) {
      const friendly = friendlyError(cause);
      setError(friendly.message);
      setErrorDetail(friendly.detail);
    } finally {
      setLoading(false);
    }
  }, [refreshBuddies]);

  async function loadMore(){setLoadingMore(true);try{const result=await learningApi.listChatSessions({limit:100,offset:sessions.length});setSessions(current=>[...current,...result.sessions.filter(item=>!current.some(old=>old.id===item.id))]);setTotal(result.total);await refreshBuddies();}catch(cause){setError(friendlyError(cause).message);}finally{setLoadingMore(false);}}

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load, refreshKey]);

  useEffect(() => {
    const refresh = () => void load();
    window.addEventListener('forma:chat-history-changed', refresh);
    return () => window.removeEventListener('forma:chat-history-changed', refresh);
  }, [load]);

  useEffect(() => {
    if (renamingId) renameInput.current?.focus();
  }, [renamingId]);

  useEffect(() => {
    if (!menuId) return;
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') { setMenuId(null); setConfirmDeleteId(null); } };
    window.addEventListener('keydown', close);
    return () => window.removeEventListener('keydown', close);
  }, [menuId]);

  const groups = useMemo(() => {
    const now = new Date();
    const buckets = new Map<string, ChatSessionSummary[]>();
    for (const item of [...sessions].sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt))) {
      const filter = fixedBuddyId || buddyFilter;
      if (filter && buddies.snapshot?.chats[item.id] !== filter) continue;
      if (![item.title,item.preview,item.goal,courses.find(course=>course.id===item.courseId)?.name,buddies.snapshot?.profiles.find(buddy=>buddy.id===buddies.snapshot?.chats[item.id])?.name].filter(Boolean).join(' ').toLowerCase().includes(search.toLowerCase())) continue;
      if (courseFilter && item.courseId !== courseFilter) continue;
      const group = pinned.includes(item.id) ? 'date:Pinned' : `date:${groupFor(item.updatedAt, now)}`;
      if (!buckets.has(group)) buckets.set(group, []);
      buckets.get(group)!.push(item);
    }
    return ['Pinned',...GROUP_ORDER].map(group => `date:${group}`).filter(key => buckets.has(key)).map(key => ({ group: key.slice(5), key, items: buckets.get(key)! }));
  }, [sessions, courseFilter, buddies.snapshot, buddyFilter, fixedBuddyId, search, pinned, courses]);

  async function commitRename(id: string) {
    const title = draft.trim();
    if (!title || busyId) return;
    setBusyId(id);
    try {
      const updated = await learningApi.renameChatSession(id, title);
      setSessions(current => current.map(item => item.id === id ? { ...item, title: updated.title || title } : item));
      setRenamingId(null);
      setMenuId(null);
    } catch (cause) {
      const friendly = friendlyError(cause);
      setError(friendly.message);
      setErrorDetail(friendly.detail);
    } finally {
      setBusyId(null);
    }
  }

  async function commitDelete(id: string) {
    if (busyId) return;
    setBusyId(id);
    try {
      await learningApi.deleteChatSession(id);
      setSessions(current => current.filter(item => item.id !== id));
      setMenuId(null);
      setConfirmDeleteId(null);
      if (id === activeSessionId) onOpen(null);
    } catch (cause) {
      const friendly = friendlyError(cause);
      setError(friendly.message);
      setErrorDetail(friendly.detail);
    } finally {
      setBusyId(null);
    }
  }

  async function regenerateTitle(id: string) {
    if (busyId) return;
    setBusyId(id); setMenuId(null);
    try {
      const updated = await learningApi.regenerateChatTitle(id);
      setSessions(current => current.map(item => item.id === id ? { ...item, title: updated.title || item.title } : item));
      window.dispatchEvent(new CustomEvent('forma:chat-title-changed'));
    } catch (cause) {
      const friendly = friendlyError(cause);
      setError(friendly.message); setErrorDetail(cause instanceof Error ? cause.message : friendly.detail);
    } finally { setBusyId(null); }
  }

  return (
    <div className={styles.history}>
      <div className={styles.filters}>
        <label>Conversations<input type="search" aria-label="Search conversations" placeholder="Search chats…" value={search} onChange={event => setSearch(event.target.value)} /></label>
        {!fixedBuddyId ? <select aria-label="Filter conversations by buddy" value={buddyFilter} onChange={event => setBuddyFilter(event.target.value)}><option value="">All buddies</option>{buddies.snapshot?.profiles.map(buddy => <option key={buddy.id} value={buddy.id}>{buddy.name}</option>)}</select> : null}
      </div>
      {loading ? (
        <div aria-busy="true" aria-label="Loading chat history" className={styles.loading}>
          {[0, 1, 2].map(index => <span key={index} className={styles.skeleton} />)}
        </div>
      ) : null}
      {!loading && error ? (
        <div className={styles.state} role="alert">
          <p><strong>{error}</strong></p>
          {errorDetail ? <p className={styles.detail}>{errorDetail}</p> : null}
          <button type="button" className={styles.retry} onClick={() => void load()}>Retry</button>
        </div>
      ) : null}
      {!loading && !error && groups.length === 0 ? (
        <div className={styles.state}>
          <p>{search || buddyFilter ? 'No matching conversations. Try another search or buddy.' : 'No conversations yet. Ask your first question and it will appear here.'}</p>
          <button type="button" className={styles.retry} onClick={() => onOpen(null)}><Plus size={14} />New chat</button>
        </div>
      ) : null}
      {!loading && !error ? groups.map(({ group, key, items }) => (
        <div key={key}>
          <div className={styles.groupLabel}>{group}</div>
          <ul className={styles.list}>
            {items.map(item => (
              <li key={item.id} className={styles.row}>
                {renamingId === item.id ? (
                  <form
                    className={styles.renameForm}
                    onSubmit={event => { event.preventDefault(); void commitRename(item.id); }}
                  >
                    <input
                      ref={renameInput}
                      value={draft}
                      maxLength={120}
                      aria-label="Conversation title"
                      onChange={event => setDraft(event.target.value)}
                      onKeyDown={event => { if (event.key === 'Escape') { setRenamingId(null); setMenuId(null); } }}
                    />
                  </form>
                ) : (
                  <button
                    type="button"
                    title={item.title}
                    aria-current={item.id === activeSessionId ? 'true' : undefined}
                    className={'nav-item ' + styles.item + (item.id === activeSessionId ? ' active' : '')}
                    onClick={() => onOpen(item.id)}
                  >
                    <span className={styles.itemBody}><span className={styles.title}>{item.title}</span><span className={styles.preview}>{item.preview || item.goal}</span><span className={styles.meta}>{relativeTime(item.updatedAt, new Date())}<span className={styles.courseTag}>{buddies.snapshot?.profiles.find(p=>p.id===buddies.snapshot?.chats[item.id])?.name||'Buddy'}</span>{item.courseId ? <span className={styles.courseTag}>{courses.find(course => course.id === item.courseId)?.name || 'Course'}</span> : null}</span></span>
                  </button>
                )}
                {renamingId !== item.id ? (
                  <button
                    type="button"
                    className={styles.dots}
                    aria-label={`Conversation actions for ${item.title}`}
                    aria-expanded={menuId === item.id}
                    onClick={() => { setMenuId(menuId === item.id ? null : item.id); setConfirmDeleteId(null); }}
                  >
                    <Ellipsis size={15} />
                  </button>
                ) : null}
                {menuId === item.id ? (
                  <>
                    <button type="button" aria-hidden tabIndex={-1} className={styles.scrim} onClick={() => { setMenuId(null); setConfirmDeleteId(null); }} />
                    <div className={styles.menu} role="menu" aria-label={`Actions for ${item.title}`}>
                      <button type="button" role="menuitem" onClick={()=>{togglePin(item.id);setMenuId(null);}}>{pinned.includes(item.id)?'Unpin':'Pin on this device'}</button>
                      <button type="button" role="menuitem" onClick={() => { setDraft(item.title); setRenamingId(item.id); setMenuId(null); setConfirmDeleteId(null); }}>Rename</button>
                      <button type="button" role="menuitem" disabled={busyId === item.id || item.turnCount === 0} onClick={() => void regenerateTitle(item.id)}>Regenerate title</button>
                      {confirmDeleteId === item.id ? (
                        <button type="button" role="menuitem" className={styles.danger} disabled={busyId === item.id} onClick={() => void commitDelete(item.id)}>
                          {busyId === item.id ? 'Deleting…' : 'Confirm delete'}
                        </button>
                      ) : (
                        <button type="button" role="menuitem" className={styles.danger} onClick={() => setConfirmDeleteId(item.id)}>Delete</button>
                      )}
                    </div>
                  </>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      )) : null}
      {!loading&&!error&&sessions.length<total?<button className={styles.retry} disabled={loadingMore} onClick={()=>void loadMore()}>{loadingMore?'Loading…':'Load older chats'}</button>:null}
    </div>
  );
}
