import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { VoiceDock } from '@/components/voice/voice-dock';
import { observeVoice } from '@/lib/voice/client';

const { request, requestStream } = vi.hoisted(() => ({ request: vi.fn(async () => ({})), requestStream: vi.fn() }));
vi.mock('@/lib/api', () => ({ request, requestStream }));
let root: Root; let container: HTMLDivElement;
beforeEach(() => { (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true; container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container); vi.clearAllMocks(); });
afterEach(() => { act(() => root.unmount()); container.remove(); });
const props = { session: { id: 'voice', chatId: 'chat', status: 'active', epoch: 0, sequence: 0, expiresAt: 9999999999, url: 'wss://test', token: 'token' }, state: 'Listening', error: '', muted: false, captions: true, events: [], setup: false, devices: [], device: '', onDevice: vi.fn(), onStart: vi.fn(), onDismiss: vi.fn(), onEnd: vi.fn(), onMute: vi.fn(), onStop: vi.fn(), onCaptions: vi.fn(), onOpen: vi.fn(), onResume: vi.fn() };

it('keeps explicit mic, speech and end controls separate', () => {
  act(() => root.render(<VoiceDock {...props} />));
  act(() => (container.querySelector('[aria-label="Mute microphone"]') as HTMLButtonElement).click());
  act(() => (container.querySelector('[aria-label="Stop Buddy speaking"]') as HTMLButtonElement).click());
  act(() => [...container.querySelectorAll('button')].find(b => b.textContent === 'End')!.click());
  expect(props.onMute).toHaveBeenCalledOnce(); expect(props.onStop).toHaveBeenCalledOnce(); expect(props.onEnd).toHaveBeenCalledOnce();
});

it('shows consent before capturing and offers a text exit', () => {
  act(() => root.render(<VoiceDock {...props} session={null} setup />));
  expect(container.querySelector('[role="dialog"]')?.textContent).toContain('microphone audio is processed');
  expect(container.textContent).toContain('Keep typing'); expect(props.onStart).not.toHaveBeenCalled();
});

it('confirms the exact action hash instead of issuing a fresh mutation', async () => {
  act(() => root.render(<VoiceDock {...props} events={[{ sequence: 1, voiceSessionId: 'voice', type: 'action.created', callId: 'action', status: 'awaiting_confirmation', argumentsHash: 'a'.repeat(64), tool: 'reminder_cancel' }]} />));
  await act(async () => [...container.querySelectorAll('button')].find(b => b.textContent === 'Confirm')!.click());
  expect(request).toHaveBeenCalledWith('/v1/voice/actions/action/confirm', expect.objectContaining({ body: JSON.stringify({ arguments_hash: 'a'.repeat(64), approve: true }) }));
});

it('offers spoken replies from typed input without choosing microphone start', () => {
  const textStart = vi.fn();
  act(() => root.render(<VoiceDock {...props} session={null} setup onStartText={textStart} />));
  act(() => [...container.querySelectorAll('button')].find(b => b.textContent === 'Start with text')!.click());
  expect(textStart).toHaveBeenCalledOnce();
  expect(props.onStart).not.toHaveBeenCalled();
});

it('deduplicates replayed events across arbitrary byte boundaries', async () => {
  const first = JSON.stringify({ sequence: 1, voiceSessionId: 'voice', type: 'turn.started', text: 'Quiz' });
  const last = JSON.stringify({ sequence: 2, voiceSessionId: 'voice', type: 'session.ended' });
  const value = `data: ${first}\n\ndata: ${first}\n\ndata: ${last}\n\n`;
  const chunks = [value.slice(0, 17), value.slice(17, 70), value.slice(70)];
  requestStream.mockResolvedValue({ body: { getReader: () => ({ read: async () => chunks.length ? { done: false, value: new TextEncoder().encode(chunks.shift()!) } : { done: true } }) } });
  const receive = vi.fn();
  await observeVoice('voice', new AbortController().signal, receive);
  expect(receive.mock.calls.map(args => args[0].sequence)).toEqual([1, 2]);
});
