import { act, useLayoutEffect } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useDictation } from '@/hooks/use-dictation';

const mocks = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock('@/lib/api', () => ({ request: mocks.request }));
vi.mock('@/lib/account-session', () => ({ ACCOUNT_CHANGED: 'test-account-change' }));
let hook: ReturnType<typeof useDictation>, root: Root, container: HTMLDivElement;
const stop = vi.fn(), closeAudio = vi.fn(async () => {});
class Socket {
  static OPEN = 1;
  static last: Socket;
  readyState = 1;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  send = vi.fn();
  close = vi.fn(() => { this.readyState = 3; this.onclose?.(); });
  constructor() { Socket.last = this; }
  receive(value: object) { this.onmessage?.({ data: JSON.stringify(value) }); }
}
class Audio {
  sampleRate = 48000;
  audioWorklet = { addModule: vi.fn(async () => {}) };
  destination = {};
  resume = vi.fn(async () => {});
  close = closeAudio;
  createMediaStreamSource() { return { connect: vi.fn() }; }
  createGain() { return { gain: { value: 1 }, connect: vi.fn() }; }
}
class Worklet { port: { onmessage: ((event: { data: object }) => void) | null; postMessage: () => void } = { onmessage: null, postMessage: () => this.port.onmessage?.({ data: { type: 'flushed' } }) }; connect = vi.fn(); disconnect = vi.fn(); }
function Harness() { const capture = useDictation(); useLayoutEffect(() => { hook = capture; }); return null; }
beforeEach(() => {
  vi.clearAllMocks();
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.stubGlobal('WebSocket', Socket); vi.stubGlobal('AudioContext', Audio); vi.stubGlobal('AudioWorkletNode', Worklet);
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia: vi.fn(async () => ({ getTracks: () => [{ stop }] })) } });
  mocks.request.mockImplementation(async (path: string) => path.endsWith('/capability') ? { available: true } : path.endsWith('/sessions') ? { id: 'one', ticket: 'ticket', url: 'wss://backend.test/v1/dictation/stream', maxSeconds: 90 } : {});
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
  act(() => root.render(<Harness/>));
});
afterEach(() => { act(() => root.unmount()); container.remove(); vi.unstubAllGlobals(); });

describe('dictation microphone lifecycle', () => {
  it('finalizes text, stops microphone immediately, and only invokes draft callback', async () => {
    const insert = vi.fn();
    await act(async () => { await hook.start(insert); });
    act(() => { Socket.last.onopen?.(); Socket.last.receive({ type: 'ready', sessionId: 'one' }); });
    expect(hook.phase).toBe('listening');
    act(() => Socket.last.receive({ type: 'transcript.final', sessionId: 'one', sequence: 1, segmentId: 'a', text: 'Explain gravity.' }));
    act(() => hook.finish());
    expect(stop).toHaveBeenCalledOnce();
    expect(hook.phase).toBe('finalizing');
    expect(insert).not.toHaveBeenCalled();
    act(() => Socket.last.receive({ type: 'completed', sessionId: 'one' }));
    expect(insert).toHaveBeenCalledWith('Explain gravity.');
    expect(closeAudio).toHaveBeenCalled();
  });
  it('ignores late results after cancel and preserves finalized text on interruption', async () => {
    const insert = vi.fn(); await act(async () => { await hook.start(insert); });
    act(() => Socket.last.receive({ type: 'ready', sessionId: 'one' }));
    act(() => Socket.last.receive({ type: 'transcript.final', sessionId: 'one', sequence: 1, segmentId: 'a', text: 'Keep this.' }));
    act(() => Socket.last.onerror?.());
    expect(hook.phase).toBe('error'); expect(hook.text).toBe('Keep this.');
    act(() => hook.cancel());
    act(() => Socket.last.receive({ type: 'completed', sessionId: 'one' }));
    expect(hook.phase).toBe('idle'); expect(insert).not.toHaveBeenCalled();
  });
  it('stops a microphone permission result that arrives after cancellation', async () => {
    let permit!: (stream: object) => void;
    vi.mocked(navigator.mediaDevices.getUserMedia).mockImplementation(() => new Promise(resolve => { permit = resolve as typeof permit; }));
    let pending!: Promise<void>;
    await act(async () => { pending = hook.start(); await Promise.resolve(); });
    act(() => hook.cancel());
    await act(async () => { permit({ getTracks: () => [{ stop }] }); await pending; });
    expect(stop).toHaveBeenCalledOnce(); expect(hook.phase).toBe('idle');
  });
});
