import type {TutorChatContext} from '@/components/compact-tutor-chat';
export const SIDE_CHAT_OPEN='openlearn:side-chat-open';
export function openSideChat(context:TutorChatContext){window.dispatchEvent(new CustomEvent(SIDE_CHAT_OPEN,{detail:{...context,sourceLabel:context.title,id:crypto.randomUUID()}}));}
