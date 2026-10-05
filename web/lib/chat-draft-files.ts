import type { ChatAttachment,ChatNoteMention } from '@/components/chat-composer';
// Raw File objects stay local for this visit; committed material associations stay on the server.
export const chatDraftFiles=new Map<string,{attachments:ChatAttachment[];notes:ChatNoteMention[]}>();
export function clearChatDraftFiles(){chatDraftFiles.clear();}
