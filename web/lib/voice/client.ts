import { request, requestStream } from '../api';

export type VoiceFocus = { revision: number; note_id?: string | null; quiz_id?: string | null; presentation_id?: string | null; lesson_id?: string | null; visualization_id?: string | null; expected_revision?: number | null };
export type VoiceSession = { id: string; chatId: string; status: string; epoch: number; sequence: number; expiresAt: number; token: string; url: string };
export type VoiceEvent = { sequence: number; type: string; voiceSessionId: string; text?: string; epoch?: number; segmentId?: string; callId?: string; tool?: string; status?: string; arguments?: Record<string, unknown>; argumentsHash?: string; confirmationMessage?: string; userMessage?: string; message?: string; result?: Record<string, unknown>; uiIntent?: { action: string; targetId?: string }; artifactRef?: { kind: string; id: string } };
export const VOICE_FOCUS = 'openlearn-voice-focus';
export const VOICE_REFRESH = 'openlearn-voice-refresh';
export function reportVoiceFocus(focus: Omit<VoiceFocus, 'revision'>) {
  window.dispatchEvent(new CustomEvent(VOICE_FOCUS, { detail: focus }));
}

export const voiceApi = {
  capabilities: () => request<{ enabled: boolean; message: string }>('/v1/voice/capabilities'),
  create: (chatId: string, focus: VoiceFocus) => request<VoiceSession>('/v1/voice/sessions', { method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body: JSON.stringify({ chat_id: chatId, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone, language: 'en', consent: true, focus }) }),
  refreshToken: (sid: string, signal?: AbortSignal) => request<{ url: string; token: string }>(`/v1/voice/sessions/${encodeURIComponent(sid)}/token`, { method: 'POST', signal }),
  end: (sid: string) => request(`/v1/voice/sessions/${encodeURIComponent(sid)}/end`, { method: 'POST' }),
  interrupt: (sid: string) => request(`/v1/voice/sessions/${encodeURIComponent(sid)}/interrupt`, { method: 'POST' }),
  focus: (sid: string, focus: VoiceFocus) => request(`/v1/voice/sessions/${encodeURIComponent(sid)}/context`, { method: 'PATCH', body: JSON.stringify(focus) }),
  turn: (sid: string, text: string) => request(`/v1/voice/sessions/${encodeURIComponent(sid)}/turns`, { method: 'POST', body: JSON.stringify({ utterance_id: crypto.randomUUID(), text }) }),
  confirm: (id: string, argumentsHash: string, approve: boolean) => request(`/v1/voice/actions/${encodeURIComponent(id)}/confirm`, { method: 'POST', body: JSON.stringify({ arguments_hash: argumentsHash, approve }) }),
  cancel: (id: string) => request(`/v1/voice/actions/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
};

export async function observeVoice(sid: string, signal: AbortSignal, event: (event: VoiceEvent) => void) {
  let after = 0;
  let failures = 0;
  while (!signal.aborted) {
    try {
      const response = await requestStream(`/v1/voice/sessions/${encodeURIComponent(sid)}/events?after=${after}`, { signal });
      const reader = response.body?.getReader();
      if (!reader) throw new Error('Voice events unavailable.');
      const decoder = new TextDecoder();
      let pending = '';
      while (!signal.aborted) {
        const { value, done } = await reader.read();
        if (done) break;
        pending += decoder.decode(value, { stream: true });
        let boundary: number;
        while ((boundary = pending.indexOf('\n\n')) >= 0) {
          const frame = pending.slice(0, boundary); pending = pending.slice(boundary + 2);
          const data = frame.split('\n').find(line => line.startsWith('data: '));
          if (!data) continue;
          const item = JSON.parse(data.slice(6)) as VoiceEvent;
          if (item.voiceSessionId !== sid || !Number.isSafeInteger(item.sequence) || item.sequence <= after) continue;
          after = item.sequence; failures = 0; event(item);
          if (item.type === 'session.ended') return;
        }
      }
    } catch (cause) {
      if (signal.aborted) return;
      failures = Math.min(failures + 1, 6);
    }
    await new Promise<void>(resolve => {
      const timer = setTimeout(resolve, Math.min(1000 * 2 ** failures, 30000));
      signal.addEventListener('abort', () => { clearTimeout(timer); resolve(); }, { once: true });
    });
  }
}
