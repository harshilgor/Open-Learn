import { request, type LectureStatus, type LectureTranscriptSegment } from './api';
export type ClassPolicy={notes:boolean;materials:boolean;practice:boolean;flashcards:boolean};
export type ClassSetup={deviceId:string;materialVersionIds:string[];policy:ClassPolicy};
export type ClassOutput={id:string;windowId:string;kind:string;status:string;revision:number;error?:string;result?:{blocks?:{title:string;body:string;segmentIds:string[]}[];items?:{prompt:string;answer:string;segmentIds:string[]}[];sources?:{spanId:string;versionId:string;title:string;text:string;pageIndex:number}[];quizId?:string;deckId?:string;boundedCoverage?:boolean}};
export type ClassSnapshot={session:{id:string;revision:number;recordingId:string;sessionId:string;noteId:string;buddyId:string;courseId:string|null;title:string;deviceId:string;processing:string;cancelled:boolean;partial:boolean;sourceCorrected?:boolean;noSpeech?:boolean;watermark?:number};recording:LectureStatus;outputs:ClassOutput[];transcript:LectureTranscriptSegment[];cursor:number;hasMore:boolean;events:{id:string;cursor:number;type:string;data:unknown}[]};
export const CLASS_OPEN_EVENT='openlearn-class-open';
export function openClassWorkspace(classId:string,sessionId?:string){window.dispatchEvent(new CustomEvent(CLASS_OPEN_EVENT,{detail:{classId,sessionId}}));}
export const classApi={
  snapshot:(id:string,cursor=0)=>request<ClassSnapshot>(`/v1/class-sessions/${encodeURIComponent(id)}?cursor=${cursor}`),
  create:(recording:Record<string,unknown>,setup:ClassSetup)=>request<ClassSnapshot>('/v1/class-sessions',{method:'POST',body:JSON.stringify({recording,...setup})}),
  command:(id:string,expectedRevision:number,action:string,outputId?:string)=>request<ClassSnapshot>(`/v1/class-sessions/${encodeURIComponent(id)}/commands`,{method:'POST',body:JSON.stringify({expectedRevision,action,outputId})}),
};
