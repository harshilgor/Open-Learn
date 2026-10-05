'use client';
import {request,apiBaseUrl} from './api';
import {authenticatedFetch} from './account-session';

export type InputRequest={requestId:string;revision:number;question:string;options:string[];state:string};
export type AgentArtifact={id:string;name:string;mediaType:string;size:number};
export type AgentTask={schemaVersion:2;id:string;revision:number;sessionId:string;kind:string;message:string;status:string;phase:string;summary?:string;deckId?:string;resultReferences?:{kind:string;id:string}[];completion?:{status?:string};pendingRequests:InputRequest[];artifacts:AgentArtifact[];sources?:{id:string;title:string;canonicalUrl?:string|null;contentAvailable?:boolean}[];allowedCommands:string[];error?:string};
export type Activity={id:string;sequence:number;taskId:string;type:string;text?:string};
export type Snapshot={cursor:number;hasMore:boolean;items:Activity[];tasks:AgentTask[]};
export type Admission={handled:boolean;messageId:string;references:{kind:string;id:string}[]};

export function snapshot(sessionId:string,after?:number){return request<Snapshot>(`/v1/assistant/sessions/${encodeURIComponent(sessionId)}/activity${after===undefined?'':`?after=${after}`}`);}
export function sendMessage(body:Record<string,unknown>,key:string){return request<Admission>('/v1/assistant/messages',{method:'POST',headers:{'Idempotency-Key':key},body:JSON.stringify(body)});}
export function sendCommand(task:AgentTask,body:Record<string,unknown>){return request(`/v1/assistant/tasks/${task.id}/commands`,{method:'POST',body:JSON.stringify({schemaVersion:2,expectedRevision:task.revision,...body})});}

export async function downloadArtifact(artifact:AgentArtifact){
  const headers=new Headers();
  const desktop=(window as Window & {formaDesktop?:{apiToken?:string}}).formaDesktop?.apiToken;
  if(desktop)headers.set('X-Forma-Desktop-Token',desktop);
  const response=await authenticatedFetch(`${apiBaseUrl()}/v1/assistant/artifacts/${artifact.id}/download`,{headers});
  if(!response.ok)throw new Error('This file is unavailable. Refresh the task or check its source access.');
  const url=URL.createObjectURL(await response.blob());
  const anchor=document.createElement('a');anchor.href=url;anchor.download=artifact.name;anchor.click();
  window.setTimeout(()=>URL.revokeObjectURL(url),1000);
}
