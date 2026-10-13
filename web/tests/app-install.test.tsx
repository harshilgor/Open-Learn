import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { AppInstall } from '@/components/app-install';

vi.mock('@/lib/use-app-reduced-motion', () => ({ useAppReducedMotion: () => true }));
let root: Root;
let container: HTMLDivElement;
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.useFakeTimers(); localStorage.clear(); sessionStorage.clear();
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); vi.useRealTimers(); vi.unstubAllGlobals(); });
function visit() { act(() => root.render(<AppInstall />)); act(() => vi.advanceTimersByTime(1500)); }
function offerInstall(prompt = vi.fn(async () => undefined)) {
  const event = Object.assign(new Event('beforeinstallprompt', { cancelable: true }), { prompt, userChoice: Promise.resolve({ outcome: 'accepted' }) });
  act(() => window.dispatchEvent(event)); act(() => vi.advanceTimersByTime(1500));
  return event;
}
function returning() { localStorage.setItem('openlearn-visits-v1', '2'); }
function button(text: string) { return [...document.querySelectorAll('button')].find(node => node.textContent === text)!; }

it('does not interrupt a first visit', () => {
  visit(); offerInstall();
  expect(document.querySelector('aside[aria-label="Install Open Learn"]')).toBeNull();
});
it('remembers dismissal and allows explicitly reopening instructions', () => {
  returning(); visit(); offerInstall(); expect(document.querySelector('aside[aria-label="Install Open Learn"]')).not.toBeNull();
  act(() => button('Not now').click());
  expect(localStorage.getItem('openlearn-install-invitation-v1')).toBe('seen');
  act(() => window.dispatchEvent(new Event('openlearn:install')));
  expect(document.querySelector('[role="status"]')).not.toBeNull();
});
it('does not invite returning visitors', () => {
  localStorage.setItem('openlearn-install-invitation-v1', 'seen'); visit();
  expect(document.querySelector('[role="status"]')).toBeNull();
});
it('does not invite standalone visitors', () => {
  vi.stubGlobal('matchMedia', () => ({ matches: true })); visit();
  expect(document.querySelector('[role="status"]')).toBeNull();
});
it('waits for the browser to offer installation before inviting', () => {
  returning(); visit();
  expect(document.querySelector('aside[aria-label="Install Open Learn"]')).toBeNull();
  offerInstall();
  expect(document.querySelector('aside[aria-label="Install Open Learn"]')).not.toBeNull();
});
it('only triggers the native prompt on a click, then consumes it', async () => {
  returning(); visit();
  const prompt = vi.fn(async () => undefined);
  const event = offerInstall(prompt);
  expect(event.defaultPrevented).toBe(true); expect(prompt).not.toHaveBeenCalled();
  await act(async () => button('Install app').click());
  expect(prompt).toHaveBeenCalledTimes(1);
  expect(document.querySelector('[role="status"]')).toBeNull();
});
