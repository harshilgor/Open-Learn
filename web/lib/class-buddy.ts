import {lectureCapture} from './lecture-capture';
import {request} from './api';
export type ClassQuestionContext={classId:string;anchorMs:number;segmentRefs?:{segmentId:string;revision:number}[];noteRefs?:{blockId:string;revision:number}[];review?:boolean};
export type ClassAnswerEvidence={id:string;classId:string;anchorMs:number;availableThroughMs:number;needsReview:boolean;selectedNotes?:{blockId:string;revision:number;title:string;body:string;studentEdited:boolean}[];evidence:{segmentId:string;revision:number;startMs:number;endMs:number;text:string;speakerRole:string;confidence:number|null}[]};
export const CLASS_BUDDY_REQUEST_EVENT='openlearn-class-buddy-question';
export const CLASS_EVIDENCE_OPEN_EVENT='openlearn-class-evidence-open';
let current:{sessionId:string;context:ClassQuestionContext;recordingId?:string}|null=null;
export function setClassQuestionContext(sessionId:string|null,context:ClassQuestionContext|null,recordingId?:string){current=sessionId&&context?{sessionId,context,recordingId}:null;}
export function getClassQuestionContext(sessionId:string|null){if(!current||current.sessionId!==sessionId)return undefined;return {...current.context,anchorMs:Math.round(Math.max(current.context.anchorMs,current.recordingId&&lectureCapture.recordingId===current.recordingId?lectureCapture.elapsedMs:0))};}
export function askClassBuddy(context:ClassQuestionContext,message:string){window.dispatchEvent(new CustomEvent(CLASS_BUDDY_REQUEST_EVENT,{detail:{context,message}}));}
export const classBuddyApi={
  history:(id:string)=>request<{items:{id:string;generationId:string;question:string;answer:string;status:string;evidence:ClassAnswerEvidence}[]}>(`/v1/class-sessions/${encodeURIComponent(id)}/buddy-history`),
  evidence:(id:string,generationId:string)=>request<ClassAnswerEvidence>(`/v1/class-sessions/${encodeURIComponent(id)}/buddy-contexts/by-generation/${encodeURIComponent(generationId)}`),
  doubts:(id:string)=>request<{items:{id:string;question:string;anchorMs:number;resolution:string;revision:number}[]}>(`/v1/class-sessions/${encodeURIComponent(id)}/doubts`),
  saveDoubt:(id:string,anchorMs:number,question:string)=>request(`/v1/class-sessions/${encodeURIComponent(id)}/doubts`,{method:'POST',body:JSON.stringify({commandId:crypto.randomUUID(),anchorMs,question})}),
  resolve:(id:string,doubt:{id:string;revision:number},resolution:'open'|'resolved'|'review')=>request(`/v1/class-sessions/${encodeURIComponent(id)}/doubts/${encodeURIComponent(doubt.id)}`,{method:'PATCH',body:JSON.stringify({expectedRevision:doubt.revision,resolution})}),
};
