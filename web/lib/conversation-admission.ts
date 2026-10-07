"use client";

import { request } from './api';
import { sendMessage } from './assistant-client';
import { routeFlashcardRequest } from './flashcards-client';

type AdmissionReply = Awaited<ReturnType<typeof sendMessage>> & {
  question?: string; directive?: { kind: string; taskId?: string; action?: string };
  runtimeOwner?: string; status?: string; message?: string;
};
type Pending = { key: string; body: Record<string, unknown> };

/** Both chat surfaces admit a message once before selecting a domain execution owner. */
export async function admitConversation(message: string, sessionId: string, courseId?: string | null, previousBrowserTaskId?: string, attachments: {versionId:string;name:string}[] = [], presentation: 'conversation'|'ask'|'learn'|'quiz' = 'conversation'): Promise<AdmissionReply & { message?: string }> {
  const identity = await request<{ ownerId: string }>('/v1/account');
  const storageKey = `openlearn-conversation-admission:${identity.ownerId}:${sessionId}`;
  const saved = sessionStorage.getItem(storageKey);
  const pending: Pending = saved ? JSON.parse(saved) : {
    key: crypto.randomUUID(), body: { clientMessageId: crypto.randomUUID(), sessionId, text: message,
      ...(courseId ? { courseId } : {}), attachments, presentation, ...(previousBrowserTaskId ? { previousBrowserTaskId } : {}), timezone: Intl.DateTimeFormat().resolvedOptions().timeZone },
  };
  if (pending.body.text !== message || JSON.stringify(pending.body.attachments || []) !== JSON.stringify(attachments)) throw new Error('An earlier message is awaiting acknowledgement. Retry its original text before sending a changed request.');
  sessionStorage.setItem(storageKey, JSON.stringify(pending));
  let admission: AdmissionReply;
  try { admission = await sendMessage(pending.body, pending.key) as AdmissionReply; }
  catch (cause) {
    const status = typeof cause === 'object' && cause !== null && 'status' in cause ? Number(cause.status) : 0;
    if ([400,403,404,422].includes(status)) sessionStorage.removeItem(storageKey);
    throw cause;
  }
  const result: AdmissionReply & { message?: string } = admission;
  if (admission.directive?.kind === 'flashcards') {
    await routeFlashcardRequest(message, sessionId, courseId || undefined);
  } else if (admission.directive?.kind === 'browser_control') {
    const task = await request<{ revision: number }>(`/v1/assistant/tasks/${admission.directive.taskId}`);
    await request(`/v1/assistant/tasks/${admission.directive.taskId}/commands`, {
      method: 'POST', body: JSON.stringify({ action: admission.directive.action, expectedRevision: task.revision }),
    });
  }
  sessionStorage.removeItem(storageKey);
  window.dispatchEvent(new Event('openlearn-browser-task-changed'));
  window.dispatchEvent(new Event('openlearn-agent-activity-changed'));
  return result;
}
