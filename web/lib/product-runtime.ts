export function isDesktopApp(): boolean {
  return typeof window !== 'undefined' && Boolean((window as Window & { formaDesktop?: unknown }).formaDesktop);
}

export function isLocalWeb(): boolean {
  return typeof window !== 'undefined' && ['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname);
}

export function serviceConnectionMessage(): string {
  return isDesktopApp()
    ? 'The app cannot connect right now. Your draft is still here. Check your connection and retry.'
    : 'Open Learn is temporarily unavailable. Your draft is still here. Please retry.';
}
