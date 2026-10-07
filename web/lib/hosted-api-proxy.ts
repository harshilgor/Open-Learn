const requestHeaders = ['authorization', 'content-type', 'accept', 'last-event-id', 'idempotency-key', 'x-idempotency-key', 'if-match', 'range'];
const responseHeaders = ['content-type', 'content-disposition', 'content-range', 'accept-ranges', 'retry-after', 'etag'];

export async function proxyHostedApi(request: Request, segments: string[]): Promise<Response> {
  const configured = process.env.OPENLEARN_API_ORIGIN?.trim();
  const unavailable = () => Response.json({ detail: { code: 'service_unavailable', message: 'Open Learn is temporarily unavailable. Your draft is still here. Please retry.' } }, { status: 503, headers: { 'Cache-Control': 'no-store' } });
  if (!configured) return unavailable();
  let origin: URL;
  try {
    origin = new URL(configured);
    if (origin.protocol !== 'https:' || origin.username || origin.password || origin.pathname !== '/' || origin.search || origin.hash || ['localhost', '127.0.0.1', '[::1]'].includes(origin.hostname)) return unavailable();
  } catch { return unavailable(); }
  if (segments.some(part => !part || part === '.' || part === '..' || part.includes('/') || part.includes('\\'))) return Response.json({ detail: { code: 'invalid_path', message: 'Invalid request.' } }, { status: 400 });
  const upstream = new URL('/v1/' + segments.map(encodeURIComponent).join('/'), origin);
  upstream.search = new URL(request.url).search;
  const headers = new Headers();
  for (const name of requestHeaders) { const value = request.headers.get(name); if (value) headers.set(name, value); }
  try {
    const startedAt = performance.now();
    const response = await fetch(upstream, {
      method: request.method, headers, cache: 'no-store', redirect: 'manual', signal: request.signal,
      ...(!['GET', 'HEAD'].includes(request.method) ? { body: request.body, duplex: 'half' } : {}),
    } as RequestInit);
    // Do not forward redirects that could leak the learner's credentials.
    if (response.status >= 300 && response.status < 400) return unavailable();
    const returned = new Headers({ 'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff' });
    const upstreamTiming = response.headers.get('server-timing');
    returned.set('Server-Timing', [upstreamTiming, `proxy_upstream;dur=${(performance.now() - startedAt).toFixed(1)}`].filter(Boolean).join(', '));
    for (const name of responseHeaders) { const value = response.headers.get(name); if (value) returned.set(name, value); }
    return new Response(response.body, { status: response.status, headers: returned });
  } catch { return unavailable(); }
}
