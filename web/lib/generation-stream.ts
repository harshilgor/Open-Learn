import { authenticatedFetch } from './account-session';
import { apiBaseUrl, request, type Gear } from './api';
import type { VisualType } from './visualization-spec';

export type GenerationMode = 'ask' | 'learn';
export type GenerationRequest = { mode: GenerationMode; message: string; gear: Gear; expectedRevision: number; classificationBypassId?: string; taskId?: string; canonicalConceptIds?: string[]; action?: 'message' | 'start' | 'next' | 'repair'; visualType?: VisualType | 'auto'; noteContext?: unknown; selectedSpanIds?: string[]; selectedText?: string; selectedLessonId?: string; selectedBlockId?: string };
export type GenerationEvent = { generationId: string; sequence: number; type: string; data: Record<string, unknown> };
export type GenerationUsage = { totalTokens: number; promptTokens?: number | null; completionTokens?: number | null; usageSource: 'exact' | 'estimated'; provider?: string | null; model?: string | null };
export type GenerationDescriptor = { id: string; sessionId: string; mode: GenerationMode; status: string; sequence: number; provider: string; model: string; journeyRevision?: number | null; finalRevision?: number | null; errorCode?: string | null; metrics?: Record<string, number | string | boolean | null> | null };
export type GenerationCallbacks = { onEvent: (event: GenerationEvent) => void; onReconnect?: () => void; onDescriptor?: (descriptor: GenerationDescriptor) => void; onSequence?: (sequence: number) => void };

function headers(extra: HeadersInit = {}): Headers {
  const value = new Headers(extra);
  value.set('Accept', 'text/event-stream');
  const token = (window as Window & { formaDesktop?: { apiToken?: string } }).formaDesktop?.apiToken;
  if (token) value.set('X-Forma-Desktop-Token', token);
  return value;
}

/** Shared Ask/Learn observer. Delivery is at-least-once, so sequence filtering is mandatory. */
export class GenerationStream {
  private controller: AbortController | null = null;
  private stopped = false;
  wasCancelled = false;
  private sequence = 0;
  descriptor: GenerationDescriptor | null = null;

  async start(sessionId: string, body: GenerationRequest, callbacks: GenerationCallbacks): Promise<GenerationDescriptor> {
    const key = crypto.randomUUID();
    const descriptor = await request<GenerationDescriptor>(`/v1/sessions/${encodeURIComponent(sessionId)}/generations`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key }, body: JSON.stringify(body),
    });
    this.descriptor = descriptor;
    this.sequence = descriptor.sequence || 0;
    callbacks.onDescriptor?.(descriptor);
    await this.observe(callbacks);
    return descriptor;
  }

  async resume(descriptor: GenerationDescriptor, callbacks: GenerationCallbacks): Promise<void> {
    this.descriptor = descriptor;
    this.sequence = descriptor.sequence || 0;
    callbacks.onDescriptor?.(descriptor);
    await this.observe(callbacks);
  }

  async stop(): Promise<void> {
    this.stopped = true;
    this.wasCancelled = true;
    this.controller?.abort();
    if (this.descriptor) await request(`/v1/generations/${encodeURIComponent(this.descriptor.id)}/cancel`, { method: 'POST' });
  }

  private async observe(callbacks: GenerationCallbacks): Promise<void> {
    if (!this.descriptor) return;
    let retries = 0;
    while (!this.stopped) {
      this.controller = new AbortController();
      try {
        const response = await authenticatedFetch(`${apiBaseUrl()}/v1/generations/${encodeURIComponent(this.descriptor.id)}/events?after=${this.sequence}`, {
          headers: headers(this.sequence ? { 'Last-Event-ID': String(this.sequence) } : {}), signal: this.controller.signal,
        });
        if (!response.ok || !response.body) throw new Error(`Could not reconnect to generation (${response.status}).`);
        retries = 0;
        const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = '';
        while (!this.stopped) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const frames = buffer.split('\n\n'); buffer = frames.pop() || '';
          for (const frame of frames) this.apply(frame, callbacks);
          if (this.isTerminal()) return;
        }
      } catch (cause) {
        if (this.stopped || (cause instanceof DOMException && cause.name === 'AbortError')) return;
        retries += 1;
        if (retries > 5) throw new Error('The live response connection was lost. Reload to recover the saved conversation.');
        callbacks.onReconnect?.();
        await new Promise(resolve => window.setTimeout(resolve, Math.min(1000 * 2 ** retries, 8000)));
      }
    }
  }

  private terminal = false;
  private isTerminal() { return this.terminal; }
  private apply(frame: string, callbacks: GenerationCallbacks) {
    const data = frame.split('\n').find(line => line.startsWith('data:'))?.slice(5).trim();
    if (!data) return;
    let event: GenerationEvent;
    try { event = JSON.parse(data) as GenerationEvent; } catch { return; }
    if (event.sequence <= this.sequence) return;
    this.sequence = event.sequence;
    callbacks.onSequence?.(this.sequence);
    callbacks.onEvent(event);
    if (['generation.completed', 'generation.cancelled', 'generation.error'].includes(event.type)) this.terminal = true;
  }
}
