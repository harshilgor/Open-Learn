import { proxyHostedApi } from '@/lib/hosted-api-proxy';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
export const maxDuration = 300;
type Context = { params: Promise<{ path: string[] }> };
async function forward(request: Request, context: Context) {
  return proxyHostedApi(request, (await context.params).path);
}
export { forward as GET, forward as POST, forward as PUT, forward as PATCH, forward as DELETE, forward as HEAD };
