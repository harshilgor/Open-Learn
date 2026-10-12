/** Tab-local operator preference. Never carries account data across tabs. */
export function performanceEnabled(): boolean {
  if (typeof window === 'undefined') return false;
  const choice = new URLSearchParams(window.location.search).get('performance');
  try {
    if (choice === '0') window.sessionStorage.removeItem('openlearn-performance');
    if (choice === '1') window.sessionStorage.setItem('openlearn-performance', '1');
    return choice === '1' || (choice !== '0' && window.sessionStorage.getItem('openlearn-performance') === '1');
  } catch { return choice === '1'; }
}
