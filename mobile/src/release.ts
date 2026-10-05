export const APP_VERSION = '0.1.0';
export function verifiedStoreUrl(platform: string, configured?: string): string | null {
  if (!configured) return null;
  try {
    const url = new URL(configured);
    if (url.protocol !== 'https:' || url.username || url.password || url.hash) return null;
    if (platform === 'ios' && url.hostname === 'apps.apple.com' && /\/id\d+\/?$/.test(url.pathname)) return url.href;
    if (platform === 'android' && url.hostname === 'play.google.com' && url.pathname === '/store/apps/details' && url.searchParams.get('id')) return url.href;
  } catch { /* The release has no valid store listing. */ }
  return null;
}
