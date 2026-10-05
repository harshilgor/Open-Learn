import { request } from './api';
export type Buddy = { id:string; name:string; avatar:'spark'|'owl'|'cat'|'leaf'|'planet'; color:'sage'|'blue'|'violet'|'rose'|'amber'; style:'calm'|'encouraging'|'playful'|'direct'; concise:boolean; examples:boolean; proactive:boolean; revision:number; archived:boolean };
export type BuddySnapshot = { profiles:Buddy[]; defaultBuddyId:string; courses:Record<string,string>; chats:Record<string,string>; modes:Record<string,string>; responsibilities:Record<string,number>; lastChats:Record<string,string>; unread:Record<string,number>; classes:{classId?:string|null;id:string;title:string;status:string;courseId:string|null;noteId:string;startedAt:number;buddyId:string|null}[] };
export type BuddyInput = Omit<Buddy,'id'|'revision'|'archived'>;
export const buddyApi = {
  remember:(buddy:string,sessionId:string)=>request(`/v1/buddies/${buddy}/navigation`,{method:'PUT',body:JSON.stringify({sessionId})}),
  snapshot:()=>request<BuddySnapshot>('/v1/buddies'),
  mode:(session:string,mode:string)=>request(`/v1/buddies/chats/${session}/mode`,{method:'PUT',body:JSON.stringify({mode})}),
  save:(input:BuddyInput, existing?:Buddy)=>request<Buddy>(existing?`/v1/buddies/${existing.id}`:'/v1/buddies',{method:existing?'PATCH':'POST',body:JSON.stringify({...input,expectedRevision:existing?.revision})}),
  assign:(course:string,buddyId:string|null)=>request<BuddySnapshot>(`/v1/buddies/courses/${course}`,{method:'PUT',body:JSON.stringify({buddyId})}),
  makeDefault:(id:string)=>request<BuddySnapshot>(`/v1/buddies/${id}/default`,{method:'POST'}),
  archive:(buddy:Buddy,replacementId:string)=>request<BuddySnapshot>(`/v1/buddies/${buddy.id}/archive`,{method:'POST',body:JSON.stringify({replacementId,expectedRevision:buddy.revision})}),
};
