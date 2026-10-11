// Vercel and CI use the same asset preparation + Next.js production compiler.
import { spawnSync } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import nextEnv from '@next/env';

const root = fileURLToPath(new URL('../', import.meta.url));
nextEnv.loadEnvConfig(root, false);
const contract = JSON.parse(await readFile(new URL('../../deploy/release-contract.json', import.meta.url), 'utf8'));
if (process.env.VERCEL_ENV === 'production' || process.env.OPENLEARN_ENFORCE_RELEASE_GATE === '1') {
  const configured = process.env.OPENLEARN_API_ORIGIN || process.env.NEXT_PUBLIC_LEARNING_API_URL;
  if (!configured) throw new Error('Production build requires the backend origin for its release gate.');
  const origin = new URL(configured);
  if (origin.protocol !== 'https:' || origin.username || origin.password || origin.pathname !== '/' || origin.search || origin.hash) throw new Error('Invalid production backend origin.');
  const publicValue = process.env.NEXT_PUBLIC_LEARNING_API_URL?.trim();
  if (publicValue) {
    const publicOrigin = new URL(publicValue);
    if (publicOrigin.origin !== origin.origin || publicOrigin.pathname !== '/' || publicOrigin.username || publicOrigin.password || publicOrigin.search || publicOrigin.hash) {
      throw new Error('Compiled public API configuration differs from the release backend. Update the matching environment before building.');
    }
  }
  const response = await fetch(new URL('/release', origin), { signal: AbortSignal.timeout(15000), redirect: 'error' });
  if (!response.ok) throw new Error('Backend release metadata is unavailable. Deploy the compatible backend first.');
  const release = await response.json();
  if (release.protocolVersion !== contract.protocolVersion || release.schema?.compatible !== true ||
      JSON.stringify([...release.schema.actualHeads].sort()) !== JSON.stringify([...contract.schemaHeads].sort()) ||
      !contract.requiredCapabilities.every(value => release.capabilities?.includes(value))) {
    throw new Error('Backend protocol, schema, or capabilities are incompatible with this frontend.');
  }
  console.log('Backend release gate passed.');
} else {
  console.log('Offline production compiler check; live release qualification is separate.');
}
for (const [entry, args] of [['build-visual-assets.mjs', []], ['../node_modules/next/dist/bin/next', ['build', '--webpack']]]) {
  const result = spawnSync(process.execPath, [fileURLToPath(new URL(entry, import.meta.url)), ...args], { cwd: root, stdio: 'inherit', windowsHide: true });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status || 1);
}
