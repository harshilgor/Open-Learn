import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { useMobileViewport } from '@/hooks/use-mobile-viewport';
let root: Root, container: HTMLDivElement;
let viewport: EventTarget & { height: number };
function Probe() { const ref = useMobileViewport(); return <div ref={ref}><textarea aria-label="Draft" /></div>; }
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
  viewport = Object.assign(new EventTarget(), { height: 844 });
  vi.stubGlobal('visualViewport', viewport);
  vi.stubGlobal('innerHeight', 844);
  vi.stubGlobal('matchMedia', () => ({ matches: true }));
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { callback(0); return 1; });
  vi.stubGlobal('cancelAnimationFrame', vi.fn());
});
afterEach(() => { act(() => root.unmount()); container.remove(); vi.unstubAllGlobals(); });
it('fits the visible mobile viewport and marks keyboard space only while editing', async () => {
  await act(async () => root.render(<Probe />));
  const shell = container.firstElementChild as HTMLElement;
  expect(shell.style.getPropertyValue('--mobile-viewport-height')).toBe('844px');
  viewport.height = 500;
  act(() => viewport.dispatchEvent(new Event('resize')));
  expect(shell.dataset.keyboardOpen).toBe('false');
  act(() => container.querySelector('textarea')!.focus());
  expect(shell.dataset.keyboardOpen).toBe('true');
  expect(shell.style.getPropertyValue('--mobile-viewport-height')).toBe('500px');
  act(() => container.querySelector('textarea')!.blur());
  expect(shell.dataset.keyboardOpen).toBe('false');
});
it('removes the override after returning to a desktop breakpoint', async () => {
  await act(async () => root.render(<Probe />));
  vi.stubGlobal('matchMedia', () => ({ matches: false }));
  act(() => window.dispatchEvent(new Event('resize')));
  const shell = container.firstElementChild as HTMLElement;
  expect(shell.style.getPropertyValue('--mobile-viewport-height')).toBe('');
  expect(shell.dataset.keyboardOpen).toBeUndefined();
});
