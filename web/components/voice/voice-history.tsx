"use client";
import { useEffect, useState } from 'react';
import { request } from '@/lib/api';
import { openWorkspaceNote, openWorkspaceQuiz, openWorkspaceFlashcards } from '@/lib/workspace-events';
import { voiceApi, VOICE_REFRESH, type VoiceEvent } from '@/lib/voice/client';

type Receipt = { id: string; status: string; data: { tool?: string; text?: string; result?: VoiceEvent } };
type Detail = { turns: Receipt[]; speech: Receipt[]; actions: Receipt[] };

export function VoiceHistory({ chatId }: { chatId: string | null }) {
  const [sessions, setSessions] = useState<{ id: string; status: string }[]>([]);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    setDetail(null); setSelected(null);
    if (chatId) void request<{ sessions: { id: string; status: string }[] }>(`/v1/voice/sessions?chat_id=${encodeURIComponent(chatId)}`).then(value => { if (active) setSessions(value.sessions); }).catch(() => { if (active) setSessions([]); });
    const update = (event: Event) => { if ((event as CustomEvent<string>).detail === chatId) setRevision(value => value+1); };
    window.addEventListener('openlearn-voice-ended', update);
    return () => { active = false; window.removeEventListener('openlearn-voice-ended', update); };
  }, [chatId, revision]);
  const load = async (id: string) => { try { const value = await request<Detail>(`/v1/voice/sessions/${encodeURIComponent(id)}`); setDetail(value); setSelected(id); setError(''); } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not load the voice session.'); } };
  const open = (intent: VoiceEvent['uiIntent']) => {
    if (!intent || !chatId) return;
    if (intent.action === 'open_quiz' && intent.targetId) openWorkspaceQuiz({ sessionId: chatId, quizId: intent.targetId, origin: 'ask' });
    else if (intent.action === 'open_note' && intent.targetId) openWorkspaceNote(intent.targetId);
    else if (intent.action === 'open_flashcards' && intent.targetId) openWorkspaceFlashcards({ deckId: intent.targetId, view: 'editor' });
    else if (intent.action === 'open_reminders') window.dispatchEvent(new Event('openlearn-voice-reminders'));
    else window.dispatchEvent(new CustomEvent(VOICE_REFRESH, { detail: chatId }));
  };
  if (!sessions.length) return null;
  return <details className="rounded-xl border border-border p-3 text-sm"><summary>Voice conversations · {sessions.length}</summary><div className="grid gap-2 py-2">
    {sessions.map((session, index) => <button key={session.id} className="min-h-11 text-left" onClick={() => void load(session.id)}>Conversation {sessions.length-index} · {session.status === 'ended' ? 'Ended' : 'Active'}</button>)}
    {error ? <p role="alert">{error}</p> : null}
    {detail ? <section aria-label="Saved voice conversation"><h3>Requests and spoken replies</h3>{detail.turns.map(turn => <p key={turn.id}><strong>You:</strong> {turn.data.text}</p>)}{detail.speech.map(segment => <p key={segment.id}><strong>Buddy:</strong> {segment.data.text} {segment.status === 'interrupted' ? '(interrupted)' : ''}</p>)}<h3>Study actions</h3>{detail.actions.map(action => <article key={action.id} className="my-2 rounded-lg border border-border p-2"><strong>{action.data.tool?.replaceAll('_',' ')}</strong><p>{action.data.result?.userMessage || action.status}</p>{action.data.result?.uiIntent ? <button className="min-h-11" onClick={() => open(action.data.result?.uiIntent)}>Open</button> : null}{action.status === 'running' || action.status === 'queued' ? <button className="min-h-11" onClick={() => void voiceApi.cancel(action.id).then(async () => { if (selected) await load(selected); }).catch(cause => setError(cause instanceof Error ? cause.message : 'Could not cancel.'))}>Cancel pending work</button> : null}</article>)}</section> : null}
  </div></details>;
}
