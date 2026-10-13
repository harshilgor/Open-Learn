import { ACCOUNT_CHANGED, sessionToken } from './account-session';

type Frame = { sequence: number; frame: string };
let accountEpoch = 0;
if (typeof window !== 'undefined') window.addEventListener(ACCOUNT_CHANGED, () => { accountEpoch++; });

/** Optional transport sharing. SQL replay, authentication and each tab's cursor remain authoritative. */
export async function sharedGenerationResponse(generationId: string, after: number, signal: AbortSignal,
  connect: (cursor: number, signal: AbortSignal) => Promise<Response>, apiOrigin = window.location.origin): Promise<Response> {
  if (process.env.NEXT_PUBLIC_OPENLEARN_SHARED_GENERATION_STREAMS !== 'true'
      || !navigator.locks || typeof BroadcastChannel === 'undefined' || !crypto.subtle) return connect(after, signal);
  const identityEpoch = accountEpoch;
  const identity = await sessionToken();
  const desktop = (window as Window & { formaDesktop?: { apiToken?: string } }).formaDesktop?.apiToken;
  if (!identity && !desktop) return connect(after, signal);
  if (signal.aborted) throw signal.reason;
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify([identity, desktop, apiOrigin, generationId])));
  if (identityEpoch !== accountEpoch) throw new DOMException('Account changed', 'AbortError');
  const key = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
  let channel: BroadcastChannel;
  try { channel = new BroadcastChannel(`openlearn-generation-${key}`); }
  catch { return connect(after, signal); }
  const peer = crypto.randomUUID();
  const network = new AbortController();
  const encoder = new TextEncoder();
  let cursor = after, closed = false, direct = false, leader = false;
  let output: ReadableStreamDefaultController<Uint8Array>;
  let lastContact = Date.now();
  let timer: number | undefined;
  let release: (() => void) | undefined;
  let history: Frame[] = [];
  let historyBytes = 0;
  const send = (message: object) => { if (!closed) channel.postMessage(message); };
  const cleanup = () => {
    if (closed) return;
    closed = true; network.abort(); release?.(); channel.close();
    if (timer !== undefined) window.clearInterval(timer);
    signal.removeEventListener('abort', abort);
    window.removeEventListener(ACCOUNT_CHANGED, accountChanged);
    document.removeEventListener('visibilitychange', visibilityChanged);
  };
  const finish = (cause?: unknown) => {
    if (closed) return;
    if (cause) output.error(cause); else output.close();
    cleanup();
  };
  function abort() { finish(signal.reason || new DOMException('Aborted', 'AbortError')); }
  function accountChanged() { finish(new DOMException('Account changed', 'AbortError')); }
  function visibilityChanged() {
    // A hidden leader yields its network stream so a visible peer can take over.
    // Existing observers reconnect from their own durable cursor.
    if (leader && document.hidden) { send({ type: 'handoff' }); finish(new Error('Stream leadership changed.')); }
  }
  function deliver(frame: string, broadcast: boolean) {
    const data = frame.split('\n').find(line => line.startsWith('data:'))?.slice(5).trim();
    if (!data) return;
    let event: { generationId?: string; sequence?: number };
    try { event = JSON.parse(data); } catch { return; }
    if (event.generationId !== generationId || !Number.isSafeInteger(event.sequence)) return;
    const sequence = event.sequence!;
    if (sequence <= cursor) return;
    if (!broadcast && sequence !== cursor + 1) { void fallback(); return; }
    cursor = sequence;
    output.enqueue(encoder.encode(`${frame}\n\n`));
    if (broadcast) {
      // Bound both retained replay and broadcast size; larger payloads use SQL replay.
      if (frame.length > 128_000) { history = []; historyBytes = 0; send({ type: 'handoff' }); return; }
      history.push({ sequence, frame }); historyBytes += frame.length;
      while (history.length > 128 || historyBytes > 512_000) historyBytes -= history.shift()!.frame.length;
      send({ type: 'frame', sequence, frame });
    }
  }
  async function pump(broadcast: boolean) {
    try {
      const response = await connect(cursor, network.signal);
      if (!response.ok || !response.body) throw new Error(`Generation transport rejected (${response.status}).`);
      const reader = response.body.getReader();
      const decoder = new TextDecoder(); let pending = '';
      try {
        while (!closed) {
          const chunk = await reader.read();
          if (chunk.done) break;
          lastContact = Date.now();
          if (broadcast) send({ type: 'heartbeat' });
          pending += decoder.decode(chunk.value, { stream: true }).replace(/\r\n/g, '\n');
          if (pending.length > 2_000_000) throw new Error('Generation frame exceeds transport bounds.');
          const frames = pending.split('\n\n'); pending = frames.pop() || '';
          for (const frame of frames) if (!closed) deliver(frame, broadcast);
        }
        if (broadcast) send({ type: 'ended' });
        finish();
      } finally { await reader.cancel().catch(() => undefined); }
    } catch (cause) {
      if (broadcast) send({ type: 'handoff' });
      finish(cause);
    }
  }
  async function fallback() {
    if (closed || direct || leader) return;
    direct = true;
    channel.onmessage = null;
    await pump(false);
  }
  const body = new ReadableStream<Uint8Array>({
    start(controller) { output = controller; },
    cancel() { if (leader) send({ type: 'handoff' }); cleanup(); },
  });
  signal.addEventListener('abort', abort, { once: true });
  window.addEventListener(ACCOUNT_CHANGED, accountChanged);
  document.addEventListener('visibilitychange', visibilityChanged);
  channel.onmessage = event => {
    if (closed || direct) return;
    const message = event.data;
    if (message?.target && message.target !== peer) return;
    lastContact = Date.now();
    if (leader && message?.type === 'hello' && typeof message.peer === 'string' && Number.isSafeInteger(message.after)) {
      if (message.after < cursor && (!history.length || message.after < history[0].sequence - 1)) {
        send({ type: 'handoff', target: message.peer });
      } else {
        for (const frame of history) if (frame.sequence > message.after) send({ type: 'frame', target: message.peer, ...frame });
        send({ type: 'heartbeat', target: message.peer });
      }
    } else if (!leader && message?.type === 'frame' && typeof message.frame === 'string' && message.frame.length <= 128_000) {
      deliver(message.frame, false);
    } else if (!leader && ['handoff', 'ended'].includes(message?.type)) { void fallback(); }
  };
  timer = window.setInterval(() => {
    if (!leader && !direct && !closed) {
      if (Date.now() - lastContact > 20_000) void fallback();
      else send({ type: 'hello', peer, after: cursor });
    }
  }, 1000);
  void navigator.locks.request(`openlearn-generation:${key}`, { ifAvailable: true }, async lock => {
    if (closed || direct) return;
    if (!lock) { send({ type: 'hello', peer, after: cursor }); return; }
    leader = true;
    const held = new Promise<void>(resolve => { release = resolve; });
    void pump(true);
    await held;
  }).catch(() => { void fallback(); });
  if (signal.aborted) abort();
  return new Response(body, { headers: { 'Content-Type': 'text/event-stream' } });
}
