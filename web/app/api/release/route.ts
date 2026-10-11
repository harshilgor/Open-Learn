import contract from '../../../../deploy/release-contract.json';
import { releaseRouting } from '@/lib/release-routing';

export const dynamic = 'force-dynamic';
export function GET(request: Request) {
  return Response.json({ protocolVersion: contract.protocolVersion, schemaHeads: contract.schemaHeads,
    requiredCapabilities: contract.requiredCapabilities,
    commit: process.env.VERCEL_GIT_COMMIT_SHA || process.env.OPENLEARN_RELEASE_SHA || 'development',
    ...releaseRouting(request.url) },
    { headers: { 'Cache-Control': 'no-store' } });
}
