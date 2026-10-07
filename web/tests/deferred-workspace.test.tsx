import { act, useEffect, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { DeferredWorkspace } from '@/components/deferred-workspace';
import { StudyOverview } from '@/components/study-overview';
let root: Root, container: HTMLDivElement;
const load = vi.fn();
function Feature() {
  const [count, setCount] = useState(0);
  useEffect(() => { load(); }, []);
  return <button onClick={() => setCount(value => value + 1)}>Draft {count}</button>;
}
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  load.mockClear();
  container = document.createElement('div'); document.body.appendChild(container);
  root = createRoot(container);
  vi.stubGlobal('matchMedia', () => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
});
afterEach(() => { act(() => root.unmount()); container.remove(); vi.unstubAllGlobals(); });
it('does not load unopened tools and retains their state after closing', async () => {
  await act(async () => root.render(<DeferredWorkspace active={false}><Feature /></DeferredWorkspace>));
  expect(load).not.toHaveBeenCalled();
  await act(async () => root.render(<DeferredWorkspace active><Feature /></DeferredWorkspace>));
  act(() => container.querySelector('button')!.click());
  await act(async () => root.render(<DeferredWorkspace active={false}><Feature /></DeferredWorkspace>));
  await act(async () => root.render(<DeferredWorkspace active><Feature /></DeferredWorkspace>));
  expect(container.textContent).toBe('Draft 1');
  expect(load).toHaveBeenCalledTimes(1);
});
it('waits until Today is expanded before mounting its mobile data', async () => {
  await act(async () => root.render(<StudyOverview><Feature /></StudyOverview>));
  expect(load).not.toHaveBeenCalled();
  await act(async () => {
    const details = container.querySelector('details')!;
    details.open = true;
    details.dispatchEvent(new Event('toggle'));
  });
  expect(load).toHaveBeenCalledTimes(1);
});
