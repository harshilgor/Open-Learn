// Open Learn private runtime using the pinned upstream CopilotKit adapter.
import { createServer } from 'node:http';
import { createRequire } from 'node:module';
import { createHmac, timingSafeEqual } from 'node:crypto';
import { resolve, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import {AsyncLocalStorage,createHook} from 'node:async_hooks';

const project = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const upstream = process.env.OPENLEARN_OPENINTELLIGENTUI_ROOT || resolve(project, 'work/research/openintelligentui-20261009');
const secret = process.env.OPENLEARN_VISUAL_INTERNAL_SECRET || '';
if (secret.length < 32) throw new Error('Run setup-openintelligentui.ps1 before starting the runtime.');
process.env.COPILOTKIT_TELEMETRY_DISABLED = 'true';
const require = createRequire(process.env.OPENLEARN_VISUAL_NODE_PACKAGE || resolve(upstream, 'apps/app/package.json'));
const load = name => import(pathToFileURL(require.resolve(name)).href);
const { CopilotRuntime, ExperimentalEmptyAdapter, copilotRuntimeNodeHttpEndpoint } = await load('@copilotkit/runtime');
const { LangGraphHttpAgent } = await load('@copilotkit/runtime/langgraph');

function authorize(ticket) {
  if (typeof ticket !== 'string' || ticket.length > 2000) throw new Error('unauthorized');
  const [payload, signature] = ticket.split('.');
  const expected = createHmac('sha256', secret).update(payload).digest();
  const actual = Buffer.from(signature || '', 'hex');
  if (expected.length !== actual.length || !timingSafeEqual(expected, actual)) throw new Error('unauthorized');
  const claim = JSON.parse(Buffer.from(payload, 'base64url').toString());
  if (claim.exp <= Date.now() / 1000 || !claim.owner || !claim.generationId) throw new Error('unauthorized');
  return claim;
}
class PrivateAgent extends LangGraphHttpAgent {
  constructor(config) { super(config); this.visualTicket = config.headers['X-OpenLearn-Visual-Ticket']; this.visualAbort = new AbortController(); }
  clone() { const copy = super.clone(); copy.visualTicket = this.visualTicket; copy.visualAbort = this.visualAbort; return copy; }
  abortRun() { this.visualAbort.abort(); super.abortRun(); }
  requestInit(input) {
    const initial = super.requestInit(input);
    const headers = new Headers(initial.headers);
    // CopilotKit may replace its agent's general headers during request setup.
    // The verified per-run ticket survives that setup and every agent clone.
    headers.set('X-OpenLearn-Visual-Ticket', this.visualTicket);
    return { ...initial, headers, signal: this.visualAbort.signal, redirect: 'error' };
  }
}
const active = new Map();
const runContext=new AsyncLocalStorage();
const promiseOwners=new WeakMap();
createHook({init(_id,type,_trigger,resource){if(type==='PROMISE'){const id=runContext.getStore();if(id)promiseOwners.set(resource,id);}}}).enable();
// The pinned SDK can reject a background fetch after a disconnected SSE
// observer. Close affected requests safely instead of taking down the service.
process.on('unhandledRejection', (reason,promise) => {
  console.warn('Visual runtime background stream rejected:', reason?.name || 'Error');
  const id=promiseOwners.get(promise);const value=active.get(id);
  if(value){value.agent.abortRun();value.res.destroy();active.delete(id);}
});
createServer(async (req, res) => {
  if (req.url === '/health' && req.method === 'GET') {
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ status: 'ok', service: 'openlearn-visual-runtime', upstreamCommit: 'f6e4388b26a64b9a0714943b08a1ce622b924eec' }));
    return;
  }
  try {
    const ticket = req.headers['x-openlearn-visual-ticket'];
    const claim = authorize(ticket);
    if (req.url !== '/copilotkit' || req.method !== 'POST') throw new Error('unauthorized');
    const chunks = []; let bytes = 0;
    for await (const chunk of req) {
      bytes += chunk.length;
      if (bytes > 128000) throw new Error('input_limit');
      chunks.push(chunk);
    }
    const body = JSON.parse(Buffer.concat(chunks).toString());
    if (!['agent/run', 'agent/stop'].includes(body.method) || body.params?.agentId !== 'default') throw new Error('unauthorized');
    const threadId = body.method === 'agent/run' ? body.body?.threadId : body.params?.threadId;
    if (threadId !== claim.generationId) throw new Error('unauthorized');
    // Input/tool definitions are constructed by Open Learn, never by a browser.
    req.body = body;
    const existing = active.get(claim.generationId);
    let runtime = existing?.runtime;
    if (body.method === 'agent/run' && runtime) throw new Error('already_running');
    const agent = existing?.agent || new PrivateAgent({ url: 'http://127.0.0.1:8123/', headers: { 'X-OpenLearn-Visual-Ticket': ticket } });
    if (!runtime) runtime = new CopilotRuntime({
      agents: { default: agent },
      a2ui: { injectA2UITool: true }, openGenerativeUI: true,
    });
    if (body.method === 'agent/run') {
      active.set(claim.generationId, {runtime,agent,res});
      res.on('close', () => { if (!res.writableFinished) agent.abortRun(); active.delete(claim.generationId); });
    }
    const handler = copilotRuntimeNodeHttpEndpoint({ endpoint: '/copilotkit', runtime, serviceAdapter: new ExperimentalEmptyAdapter() });
    await runContext.run(claim.generationId,()=>handler(req, res));
  } catch {
    if (!res.headersSent) res.writeHead(401, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ error: 'visual_runtime_request_rejected' }));
  }
}).listen(8130, '127.0.0.1', () => console.log('Open Learn visual runtime: http://127.0.0.1:8130'));
