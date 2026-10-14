import {request} from './api';
import type {ClassPolicy,ClassSnapshot} from './in-class';
export type ClassPairing={id:string;classId:string;code:string;expiresAt:number;deepLink:string;qrSvg:string;title:string};
export type CaptureStatus={run:null|{id:string;deviceId:string;epoch:number;state:string;revision:number;stale:boolean;lastSeenAt:number;audioEndMs:number;backlog:number|null;batteryPercent:number|null};commands:{id:string;state:string;runId:string;action:string;expiresAt:number}[]};
export const classDevices={
  draft:(body:{commandId:string;deviceId:string;startedAtMs:number;title:string;courseId:string|null;buddyId?:string;materialVersionIds:string[];policy:ClassPolicy})=>request<ClassSnapshot>('/v1/class-sessions/drafts',{method:'POST',body:JSON.stringify(body)}),
  pair:(id:string,deviceId:string)=>request<ClassPairing>(`/v1/class-sessions/${encodeURIComponent(id)}/pairings`,{method:'POST',body:JSON.stringify({commandId:crypto.randomUUID(),deviceId})}),
  status:(id:string,signal?:AbortSignal)=>request<CaptureStatus>(`/v1/class-sessions/${encodeURIComponent(id)}/capture-status`,{signal}),
  command:(id:string,run:NonNullable<CaptureStatus['run']>,action:'pause'|'resume'|'stop'|'handoff')=>request(`/v1/class-sessions/${encodeURIComponent(id)}/capture-commands`,{method:'POST',body:JSON.stringify({commandId:crypto.randomUUID(),runId:run.id,expectedRevision:run.revision,action})}),
};
