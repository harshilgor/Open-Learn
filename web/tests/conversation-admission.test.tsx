import { beforeEach, expect, it, vi } from 'vitest';
import { admitConversation } from '@/lib/conversation-admission';

const mocks = vi.hoisted(() => ({ request: vi.fn(), send: vi.fn(), cards: vi.fn() }));
vi.mock('@/lib/api', () => ({ request: mocks.request }));
vi.mock('@/lib/assistant-client', () => ({ sendMessage: mocks.send }));
vi.mock('@/lib/flashcards-client', () => ({ routeFlashcardRequest: mocks.cards }));
beforeEach(() => { sessionStorage.clear(); vi.clearAllMocks(); mocks.request.mockResolvedValue({ ownerId:'alice' }); mocks.send.mockResolvedValue({ messageId:'one',handled:true,status:'queued',runtimeOwner:'browser_legacy',references:[{kind:'task',id:'browser'}] }); });
it('uses the common admission endpoint without a development capability selector', async () => {
  await admitConversation('open YouTube','session');
  expect(mocks.send).toHaveBeenCalledWith(expect.objectContaining({text:'open YouTube',sessionId:'session',clientMessageId:expect.any(String)}),expect.any(String));
  expect(mocks.request).toHaveBeenCalledTimes(1);
});
it('retries an unknown acknowledgement with the original identities', async () => {
  mocks.send.mockRejectedValueOnce(new Error('connection lost'));
  await expect(admitConversation('open YouTube','session')).rejects.toThrow('connection lost');
  await admitConversation('open YouTube','session');
  expect(mocks.send.mock.calls[0]).toEqual(mocks.send.mock.calls[1]);
});
it('preserves the original request when the user attempts to change pending content', async () => {
  mocks.send.mockRejectedValueOnce(new Error('connection lost'));
  await expect(admitConversation('open YouTube','session')).rejects.toThrow();
  await expect(admitConversation('open Canvas','session')).rejects.toThrow('awaiting acknowledgement');
  expect(mocks.send).toHaveBeenCalledTimes(1);
});
it('isolates pending commands by account', async () => {
  mocks.send.mockRejectedValueOnce(new Error('connection lost'));
  await expect(admitConversation('open YouTube','session')).rejects.toThrow();
  mocks.request.mockResolvedValue({ownerId:'bob'});
  await admitConversation('open Canvas','session');
  expect(mocks.send.mock.calls[1][0].text).toBe('open Canvas');
  expect(mocks.send.mock.calls[1][1]).not.toBe(mocks.send.mock.calls[0][1]);
});
it('passes owned attachment references and previous-task causation', async () => {
  await admitConversation('research this document','session','course','previous',[{versionId:'version',name:'notes.pdf'}]);
  expect(mocks.send.mock.calls[0][0]).toMatchObject({courseId:'course',previousBrowserTaskId:'previous',attachments:[{versionId:'version',name:'notes.pdf'}]});
});
it('returns ordinary tutoring to its existing workflow', async () => {
  mocks.send.mockResolvedValue({messageId:'one',handled:false,status:'direct',references:[]});
  expect((await admitConversation('explain gravity','session')).handled).toBe(false);
  expect(mocks.cards).not.toHaveBeenCalled();
});
