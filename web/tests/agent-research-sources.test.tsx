import {act} from 'react';
import {createRoot, type Root} from 'react-dom/client';
import {beforeEach, afterEach, describe, it, expect, vi} from 'vitest';
import {ResearchSourceList} from '@/components/assistant/research-sources';

const {request} = vi.hoisted(() => ({request: vi.fn()}));
vi.mock('@/lib/api', () => ({request}));
let root: Root;
let container: HTMLDivElement;
beforeEach(() => {
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?: boolean}).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  vi.clearAllMocks();
});
afterEach(() => {act(() => root.unmount()); container.remove();});

describe('saved research sources', () => {
  it('loads the authorized source excerpt only when requested and renders it as text', async () => {
    request.mockResolvedValue({id: 'source1', title: 'Paper', excerpt: '<script>award mastery</script>', retrievedAt: '2026-10-04'});
    act(() => root.render(<ResearchSourceList sources={[{id: 'source1', title: 'Paper', canonicalUrl: 'https://www.nist.gov/paper'}]}/>));
    expect(request).not.toHaveBeenCalled();
    await act(async () => container.querySelector('button')!.click());
    expect(request).toHaveBeenCalledWith('/v1/assistant/sources/source1');
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('blockquote')!.textContent).toBe('<script>award mastery</script>');
    expect(container.textContent).toContain('not independently verified');
    expect(container.querySelector('a')!.rel).toBe('noreferrer');
  });

  it('shows expired or revoked content errors without displaying an earlier excerpt', async () => {
    request.mockRejectedValue(new Error('Source content is no longer available.'));
    act(() => root.render(<ResearchSourceList sources={[{id: 'source1', title: 'Paper', contentAvailable: false}]}/>));
    await act(async () => container.querySelector('button')!.click());
    expect(container.querySelector('[role="alert"]')!.textContent).toContain('no longer available');
    expect(container.querySelector('blockquote')).toBeNull();
  });

  it('does not link an executable URL or an embedded credential', () => {
    act(() => root.render(<ResearchSourceList sources={[
      {id: '1', title: 'Unsafe', canonicalUrl: 'javascript:alert(1)'},
      {id: '2', title: 'Credential', canonicalUrl: 'https://secret@example.org/'},
    ]}/>));
    expect(container.querySelector('a')).toBeNull();
  });
});
