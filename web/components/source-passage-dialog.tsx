"use client";

import { useCallback, useEffect, useState } from 'react';
import { BookOpen, MessageSquarePlus, MessagesSquare, Sparkles } from 'lucide-react';
import { request } from '@/lib/api';
import { WORKSPACE_PASSAGE_MENTION_EVENT, WORKSPACE_SOURCE_OPEN_EVENT } from '@/lib/workspace-events';
import { openSideChat } from '@/lib/workspace-side-chat-events';
import { Button } from './ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from './ui/dialog';

type SourceBlock = { id: string; versionId: string; pageIndex: number; kind: string; text: string };
type SourceRequest = { spanId: string; versionId?: string; title?: string };

/** Resolve a citation to its passage: quiz study context, a material version, or a bare span id. */
async function loadPassage(source: SourceRequest): Promise<SourceBlock> {
  if (source.spanId.startsWith('quiz-context:') || source.versionId?.startsWith('quiz-context:')) {
    const quizId = (source.versionId || source.spanId).slice('quiz-context:'.length);
    const context = await request<{ spanId: string; versionId: string; pageIndex: number; text: string }>(`/v1/quizzes/${encodeURIComponent(quizId)}/study-context`);
    return { id: context.spanId, versionId: context.versionId, pageIndex: 0, kind: 'study_context', text: context.text };
  }
  const versionId = source.versionId || (await request<SourceBlock>(`/v1/source-spans/${encodeURIComponent(source.spanId)}`)).versionId;
  const { blocks } = await request<{ blocks: SourceBlock[] }>(`/v1/material-versions/${encodeURIComponent(versionId)}/blocks`);
  const block = blocks.find(item => item.id === source.spanId) || blocks[0];
  if (!block) throw new Error('This cited passage is no longer available.');
  return block;
}

/**
 * Shows the exact passage behind a citation, wherever it was clicked.
 * Replaces the former Sources tab in the study panel.
 */
export function SourcePassageDialog() {
  const [source, setSource] = useState<SourceRequest | null>(null);
  const [block, setBlock] = useState<SourceBlock | null>(null);
  const [error, setError] = useState('');
  const open = useCallback((next: SourceRequest) => {
    setSource(next); setBlock(null); setError('');
    loadPassage(next).then(setBlock).catch(cause => setError(cause instanceof Error ? cause.message : 'This cited passage could not be opened.'));
  }, []);
  useEffect(() => {
    const receive = (event: Event) => { const detail = (event as CustomEvent<SourceRequest>).detail; if (detail?.spanId) open(detail); };
    window.addEventListener(WORKSPACE_SOURCE_OPEN_EVENT, receive);
    return () => window.removeEventListener(WORKSPACE_SOURCE_OPEN_EVENT, receive);
  }, [open]);
  const title = block?.kind === 'study_context' ? 'Study context' : source?.title || 'Cited passage';
  const location = block ? (block.kind === 'study_context' ? 'Not independently verified' : `Page ${block.pageIndex + 1}`) : '';
  const mention = (submit: boolean) => {
    if (!block) return;
    window.dispatchEvent(new CustomEvent(WORKSPACE_PASSAGE_MENTION_EVENT, { detail: { title: `${title}${location ? ` · ${location}` : ''}`, excerpt: block.text.slice(0, 6000), spanId: block.id, submit } }));
    setSource(null);
  };
  return <Dialog open={!!source} onOpenChange={value => { if (!value) setSource(null); }}>
    <DialogContent className="max-w-xl">
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2"><BookOpen size={18} className="text-[var(--brand)]" aria-hidden="true" />{title}</DialogTitle>
        <DialogDescription>{location || (error ? 'Unavailable' : 'Loading the passage…')}</DialogDescription>
      </DialogHeader>
      {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
      {block ? <blockquote className="max-h-[50dvh] overflow-auto whitespace-pre-wrap rounded-[12px] border border-border bg-muted px-4 py-3 text-sm leading-relaxed">{block.text}</blockquote> : !error ? <div className="h-24 animate-pulse rounded-[12px] bg-muted" aria-hidden="true" /> : null}
      {block ? <div className="flex flex-wrap gap-2" role="toolbar" aria-label="Passage actions">
        <Button size="sm" onClick={() => mention(true)}><Sparkles size={15} />Explain</Button>
        <Button size="sm" variant="outline" onClick={() => mention(false)}><MessageSquarePlus size={15} />Add to chat</Button>
        <Button size="sm" variant="outline" onClick={() => { openSideChat({ id: block.id, title, excerpt: block.text.slice(0, 6000) }); setSource(null); }}><MessagesSquare size={15} />Ask in side chat</Button>
      </div> : null}
    </DialogContent>
  </Dialog>;
}
