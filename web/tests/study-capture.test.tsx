import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { SaveToNote } from '@/components/save-to-note';

const api = vi.hoisted(() => ({ list: vi.fn(), get: vi.fn(), create: vi.fn(), update: vi.fn(), open: vi.fn() }));
vi.mock('@/lib/api', () => ({ learningApi: { listWorkspaceNotes: api.list, getWorkspaceNote: api.get, createWorkspaceNote: api.create, updateWorkspaceNote: api.update } }));
vi.mock('@/lib/workspace-events', () => ({ openWorkspaceNote: api.open }));
vi.mock('@/components/rich-content', () => ({ RichContent: ({ body }: {body:string}) => <pre>{body}</pre> }));
let root: Root, container: HTMLDivElement;
beforeEach(() => {
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT = true;
  vi.clearAllMocks(); api.list.mockResolvedValue([{id:'n1', title:'Motion'}]); api.create.mockResolvedValue({id:'new'});
  api.get.mockResolvedValue({id:'n1',title:'Motion',body:'Existing writing',revision:7,frontmatter:{course_id:'physics'}}); api.update.mockResolvedValue({id:'n1'});
  container=document.createElement('div'); document.body.appendChild(container); root=createRoot(container);
  act(() => root.render(<SaveToNote title="Velocity" body="New explanation" sessionId="session_1" messageId="message-1"/>));
});
afterEach(() => { act(() => root.unmount()); container.remove(); });
async function click(text:string) { await act(async () => { const button=[...container.querySelectorAll('button')].find(item=>item.textContent===text); if (!button) throw Error(text); button.click(); }); }
it('requires approval and preserves explanation provenance', async () => {
  await click('Save to note'); expect(api.create).not.toHaveBeenCalled(); expect(container.textContent).toContain('Preview before saving');
  await click('Confirm addition'); expect(api.create).toHaveBeenCalledWith(expect.objectContaining({body:expect.stringContaining('/s/session_1#message-1')})); expect(api.open).toHaveBeenCalledWith('new');
});
it('appends to the latest revision without replacing existing writing', async () => {
  await click('Save to note'); await act(async () => { const select=container.querySelector('select')!; select.value='n1'; select.dispatchEvent(new Event('change',{bubbles:true})); });
  await click('Confirm addition'); expect(api.update).toHaveBeenCalledWith('n1',expect.objectContaining({expectedRevision:7,body:expect.stringContaining('Existing writing\n\n---\n\nNew explanation'),frontmatter:{course_id:'physics'}}));
});
it('retains the preview when a revision conflict occurs', async () => {
  api.create.mockRejectedValue(new Error('Note changed; retry')); await click('Save to note'); await click('Confirm addition');
  expect(container.querySelector('[role="alert"]')?.textContent).toBe('Note changed; retry'); expect(api.open).not.toHaveBeenCalled(); expect(container.textContent).toContain('Confirm addition');
});
