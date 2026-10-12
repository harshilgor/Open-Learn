import { authenticatedFetch } from './account-session';
import { apiBaseUrl, request, type Gear } from './api';
import type { VisualType } from './visualization-spec';
import { beginGenerationTiming, bindGenerationTiming, recordGenerationTiming } from './api-performance';
import { sharedGenerationResponse } from './shared-generation-response';

export type GenerationMode = 'ask' | 'learn';
export type GenerationRequest = { mode: GenerationMode; presentation?: 'conversation' | 'ask' | 'learn'; message: string; gear: Gear; expectedRevision: number; clientMessageId?: string; replyToGenerationId?: string; parentGenerationId?: string; classificationBypassId?: string; taskId?: string; canonicalConceptIds?: string[]; action?: 'message' | 'start' | 'next' | 'repair'; visualType?: VisualType | 'auto'; noteContext?: unknown; selectedSpanIds?: string[]; selectedText?: string; selectedLessonId?: string; selectedBlockId?: string; pastedRanges?: { start: number; end: number }[]; clientTimezone?: string };
export type GenerationEvent = { generationId: string; sequence: number; type: string; data: Record<string, unknown> };
export type GenerationUsage = { totalTokens: number; promptTokens?: number | null; completionTokens?: number | null; usageSource: 'exact' | 'estimated'; provider?: string | null; model?: string | null };
export type GenerationDescriptor = { id: string | null; sessionId: string; mode: GenerationMode; status: string; sequence: number; provider: string; model: string; journeyRevision?: number | null; finalRevision?: number | null; errorCode?: string | null; messageId?: string | null; conversationSeq?: number | null; contextRevision?: number | null; parentGenerationId?: string | null; branchId?: string | null; relation?: string | null; branchRevision?: number | null; selectedBranchId?: string | null; cancelTargetGenerationId?: string | null; cancelTargetStatus?: string | null; accepted?: boolean; scheduledGenerationIds?: string[]; activeGenerationIds?: string[]; metrics?: Record<string, number | string | boolean | null> | null; modeSuggestion?: import('./api').ModeTransitionSuggestion | null; modeDecision?: 'stay' | 'suggest' | 'request_transition' | null; requiresModeChoice?: boolean };
export type GenerationCallbacks = { onEvent: (event: GenerationEvent) => void; onReconnect?: () => void; onDescriptor?: (descriptor: GenerationDescriptor) => void; onModeChoice?: (descriptor: GenerationDescriptor) => void; onAccepted?: (descriptor: GenerationDescriptor) => void; onSequence?: (sequence: number) => void };

function headers(extra: HeadersInit = {}): Headers {
  const value = new Headers(extra);
  value.set('Accept', 'text/event-stream');
  const token = (window as Window & { formaDesktop?: { apiToken?: string } }).formaDesktop?.apiToken;
  if (token) value.set('X-Forma-Desktop-Token', token);
  return value;
}

export class GenerationConnectionError extends Error {
  constructor(){super('Connection lost. Your message is saved; the response status could not be confirmed.');this.name='GenerationConnectionError';}
}

/** Shared Ask/Learn observer. Delivery is at-least-once, so sequence filtering is mandatory. */
export class GenerationStream {
  private controller: AbortController | null = null;
  private stopped = false;
  wasCancelled = false;
  private sequence = 0;
  private pendingTextDelta: GenerationEvent | null = null;
  private pendingTextTimer: number | null = null;
  descriptor: GenerationDescriptor | null = null;

  async start(sessionId: string, body: GenerationRequest, callbacks: GenerationCallbacks): Promise<GenerationDescriptor> {
    const key = body.clientMessageId || crypto.randomUUID();
    const requestBody = body.clientMessageId ? body : { ...body, clientMessageId: key };
    const traceId = beginGenerationTiming(key);
    const descriptor = await request<GenerationDescriptor>(`/v1/sessions/${encodeURIComponent(sessionId)}/generations`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key, 'X-OpenLearn-Trace-Id': traceId }, body: JSON.stringify(requestBody),
    }).catch(cause => { recordGenerationTiming(key, 'failed'); throw cause; });
    recordGenerationTiming(key, descriptor.requiresModeChoice ? 'mode_choice' : 'accepted');
    if (descriptor.id) bindGenerationTiming(key, descriptor.id, descriptor.metrics?.traceId);
    this.descriptor = descriptor;
    this.sequence = descriptor.sequence || 0;
    if (descriptor.id) callbacks.onDescriptor?.(descriptor);
    if (descriptor.requiresModeChoice) { callbacks.onModeChoice?.(descriptor); return descriptor; }
    callbacks.onAccepted?.(descriptor);
    if (!descriptor.id) return descriptor;
    this.terminal = ['completed','cancelled','failed','interrupted'].includes(descriptor.status);
    if (!this.terminal) await this.observe(callbacks);
    return descriptor;
  }

  async retry(sourceGenerationId: string, idempotencyKey: string, callbacks: GenerationCallbacks): Promise<GenerationDescriptor> {
    const traceId = beginGenerationTiming(idempotencyKey);
    const descriptor = await request<GenerationDescriptor>(
      `/v1/generations/${encodeURIComponent(sourceGenerationId)}/retry`,
      { method: 'POST', headers: { 'Idempotency-Key': idempotencyKey, 'X-OpenLearn-Trace-Id': traceId } },
    ).catch(cause => { recordGenerationTiming(idempotencyKey, 'failed'); throw cause; });
    recordGenerationTiming(idempotencyKey, 'accepted');
    if (descriptor.id) bindGenerationTiming(idempotencyKey, descriptor.id, descriptor.metrics?.traceId);
    this.descriptor = descriptor;
    this.sequence = descriptor.sequence || 0;
    if (descriptor.id) callbacks.onDescriptor?.(descriptor);
    callbacks.onAccepted?.(descriptor);
    if (!descriptor.id) return descriptor;
    this.terminal = ['completed','cancelled','failed','interrupted'].includes(descriptor.status);
    if (!this.terminal) await this.observe(callbacks);
    return descriptor;
  }

  async resume(descriptor: GenerationDescriptor, callbacks: GenerationCallbacks, afterSequence = descriptor.sequence || 0): Promise<void> {
    if (descriptor.id) beginGenerationTiming(descriptor.id, 'resume', typeof descriptor.metrics?.traceId === 'string' ? descriptor.metrics.traceId : undefined);
    this.descriptor = descriptor;
    this.sequence = afterSequence;
    if (descriptor.id) callbacks.onDescriptor?.(descriptor);
    this.terminal = ['completed','cancelled','failed','interrupted'].includes(descriptor.status);
    if (!this.terminal) await this.observe(callbacks);
  }

  async stop(): Promise<void> {
    this.stopped = true;
    this.wasCancelled = true;
    this.flushTextDelta(this.lastCallbacks);
    this.controller?.abort();
    if (this.descriptor?.id) await request(`/v1/generations/${encodeURIComponent(this.descriptor.id)}/cancel`, { method: 'POST' });
  }

  private async observe(callbacks: GenerationCallbacks): Promise<void> {
    this.lastCallbacks = callbacks;
    const generationId = this.descriptor?.id;
    if (!generationId) return;
    let retries = 0;
    while (!this.stopped) {
      this.controller = new AbortController();
      try {
        const response = await sharedGenerationResponse(generationId, this.sequence, this.controller.signal,
          (cursor, signal) => authenticatedFetch(`${apiBaseUrl()}/v1/generations/${encodeURIComponent(generationId)}/events?after=${cursor}`, {
            headers: headers(cursor ? { 'Last-Event-ID': String(cursor) } : {}), signal,
          }), apiBaseUrl());
        if (!response.ok || !response.body) throw new Error(`Could not reconnect to generation (${response.status}).`);
        const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = '';
        try {
        while (!this.stopped) {
          const { done, value } = await reader.read();
          if (done) break;
          retries = 0;
          buffer += decoder.decode(value, { stream: true });
          const frames = buffer.split('\n\n'); buffer = frames.pop() || '';
          for (const frame of frames) this.apply(frame, callbacks);
          if (this.isTerminal()) return;
        }
        } finally { await reader.cancel().catch(() => undefined); }
        if (!this.stopped && !this.isTerminal()) throw new Error('The response stream ended before completion.');
      } catch (cause) {
        if (this.stopped || (cause instanceof DOMException && cause.name === 'AbortError')) return;
        retries += 1;
        if (retries > 5) { recordGenerationTiming(generationId, 'disconnected'); throw new GenerationConnectionError(); }
        callbacks.onReconnect?.();
        await new Promise(resolve => window.setTimeout(resolve, Math.min(1000 * 2 ** retries, 8000)));
      }
    }
  }

  private terminal = false;
  private lastCallbacks: GenerationCallbacks | null = null;
  private isTerminal() { return this.terminal; }
  private flushTextDelta(callbacks: GenerationCallbacks | null = this.lastCallbacks) {
    if (this.pendingTextTimer !== null) window.clearTimeout(this.pendingTextTimer);
    this.pendingTextTimer = null;
    const event = this.pendingTextDelta;
    this.pendingTextDelta = null;
    if (!event || !callbacks) return;
    callbacks.onSequence?.(event.sequence);
    callbacks.onEvent(event);
  }
  private apply(frame: string, callbacks: GenerationCallbacks) {
    const data = frame.split('\n').find(line => line.startsWith('data:'))?.slice(5).trim();
    if (!data) return;
    let event: GenerationEvent;
    try { event = JSON.parse(data) as GenerationEvent; } catch { return; }
    if (event.sequence <= this.sequence) return;
    this.sequence = event.sequence;
    const terminalStatus = {'generation.completed':'completed','generation.cancelled':'cancelled','generation.interrupted':'interrupted','generation.error':'failed'}[event.type];
    if (this.descriptor) this.descriptor = {...this.descriptor, sequence: this.sequence, ...(terminalStatus ? {status: terminalStatus} : {})};
    if (event.type === 'text.delta' && typeof event.data.text === 'string') {
      if (event.data.text.trim()) recordGenerationTiming(event.generationId, 'first_text_received');
      const blockId = event.data.blockId;
      if (this.pendingTextDelta && this.pendingTextDelta.generationId === event.generationId && this.pendingTextDelta.data.blockId === blockId) {
        this.pendingTextDelta = { ...event, data: { ...event.data, text: `${String(this.pendingTextDelta.data.text || '')}${event.data.text}` } };
      } else {
        this.flushTextDelta(callbacks);
        this.pendingTextDelta = event;
      }
      if (this.pendingTextTimer === null) {
        this.pendingTextTimer = window.setTimeout(() => this.flushTextDelta(callbacks), 40);
      }
    } else {
      this.flushTextDelta(callbacks);
      callbacks.onSequence?.(this.sequence);
      callbacks.onEvent(event);
    }
    if (terminalStatus) recordGenerationTiming(event.generationId, terminalStatus === 'completed' ? 'completed' : terminalStatus === 'cancelled' ? 'cancelled' : 'failed');
    if (['generation.completed', 'generation.cancelled', 'generation.interrupted', 'generation.error'].includes(event.type)) this.terminal = true;
  }
}
