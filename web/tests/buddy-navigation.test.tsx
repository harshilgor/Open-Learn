import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import { BuddyProvider, BuddyRail } from '@/components/buddies';
vi.mock('@/lib/buddies', () => ({ buddyApi: { snapshot: vi.fn().mockRejectedValue(new Error('Service unavailable')) } }));
it('keeps navigation and Buddy creation available during an outage', async () => {
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const container = document.createElement('div'); document.body.appendChild(container);
  const root = createRoot(container), home = vi.fn(), settings = vi.fn();
  try {
    await act(async () => root.render(<BuddyProvider><BuddyRail onSwitch={vi.fn()} onHome={home} onSettings={settings}/></BuddyProvider>));
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 10)); });
    act(() => (container.querySelector('[aria-label="Home and Today"]') as HTMLButtonElement).click());
    act(() => (container.querySelector('[aria-label="Settings"]') as HTMLButtonElement).click());
    expect(home).toHaveBeenCalledOnce(); expect(settings).toHaveBeenCalledOnce();
    const plus = container.querySelector('[aria-label="Create Buddy"]') as HTMLButtonElement;
    expect(plus.disabled).toBe(false);
    act(() => plus.click());
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain('Create Buddy');
    expect(document.querySelector('[role="status"]')?.textContent).toContain('Reconnect to save');
  } finally { act(() => root.unmount()); container.remove(); }
});
