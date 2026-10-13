import { createHash } from 'node:crypto';

/** Mirror browser API selection without publishing private proxy configuration. */
export function releaseRouting(requestUrl: string) {
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(new URL(requestUrl).hostname);
  function valid(value?: string, allowLocalHttp = false): URL | null {
    try {
      const origin = new URL(value || '');
      if (origin.username || origin.password || origin.pathname !== '/' || origin.search || origin.hash) return null;
      return origin.protocol === 'https:' || (allowLocalHttp && origin.protocol === 'http:') ? origin : null;
    } catch { return null; }
  }
  const previewProxy = process.env.NODE_ENV === 'development' && local;
  const publicOrigin = previewProxy ? null : valid(process.env.NEXT_PUBLIC_LEARNING_API_URL, local);
  const transport = publicOrigin || (local && !previewProxy) ? 'configured-public-origin' : 'same-origin-proxy';
  const origin = publicOrigin || (local && !previewProxy ? new URL('http://127.0.0.1:8000') :
    valid(process.env.OPENLEARN_API_ORIGIN || (previewProxy ? 'http://127.0.0.1:8000' : ''), previewProxy));
  return { apiTransport: transport, apiOriginFingerprint: origin ? createHash('sha256').update(origin.origin).digest('hex') : null };
}
