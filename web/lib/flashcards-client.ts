import {request} from './api';
import type {Admission} from './assistant-client';
export type FlashcardSourceRef={kind:'note'|'lesson'|'material'|'quiz_attempt'|'lecture';id:string;revision:number;startOffset?:number;endOffset?:number;spanId?:string;recordingId?:string};
export type FlashcardContent={type:'qa'|'cloze';prompt:string;answer:string;explanation:string;sourceIds:string[];supportQuote:string;conceptIds?:string[]};
export type Flashcard={id:string;versionId:string;publishedVersionId:string|null;state:string;stale:boolean;content:FlashcardContent};
export type Deck={id:string;revision:number;title:string;status:string;courseId?:string|null;sessionId?:string|null;cards:Flashcard[];cardCount:number;dueCount?:number;nextOffset?:number|null;coverage:{partial:boolean;sources:{id:string;title:string;ref:FlashcardSourceRef;hash:string}[]};candidates:{id:string;reason:string;validationReason?:string;content:FlashcardContent}[]};
export type FlashcardView={deckId?:string;view?:'editor'|'review'|'library';reviewSessionId?:string;sessionId?:string;courseId?:string;sourceRefs?:FlashcardSourceRef[]};
export type FlashcardReview={id:string;revision:number;status:string;cursor:number;total:number;practice:boolean;current:null|{cardId:string;deckId:string;versionId:string;attemptId:string;type:string;prompt:string;revealed:boolean;answer?:string;explanation?:string;response?:string}};
export type FlashcardSummary={dueCount:number;courses:Record<string,number>;sessions:{id:string;status:string;cursor:number;total:number;createdAt:number}[]};
export type FlashcardGeneration={sessionId:string;courseId?:string;origin:'conversation'|'ask'|'learn'|'quiz'|'in_class'|'review';sourceRefs:FlashcardSourceRef[];objective?:string;requestedCount?:number;cardTypes?:('qa'|'cloze')[];targetDeckId?:string;expectedDeckRevision?:number;clientCommandId:string};
export const flashcardsApi={
 generate:(input:FlashcardGeneration)=>request<Admission>('/v1/flashcard-generations',{method:'POST',body:JSON.stringify(input)}),
 list:(courseId?:string,offset=0)=>request<{decks:Deck[];nextOffset:number|null}>(`/v1/flashcard-decks?offset=${offset}${courseId?`&course_id=${encodeURIComponent(courseId)}`:''}`),
 deck:(id:string,offset=0)=>request<Deck>(`/v1/flashcard-decks/${encodeURIComponent(id)}?offset=${offset}`),
 command:(deck:Pick<Deck,'id'|'revision'>,body:Record<string,unknown>)=>request<{revision:number}>(`/v1/flashcard-decks/${encodeURIComponent(deck.id)}/commands`,{method:'POST',body:JSON.stringify({expectedRevision:deck.revision,commandId:crypto.randomUUID(),...body})}),
 summary:()=>request<FlashcardSummary>('/v1/flashcard-due-summary'),
 review:(deckId?:string,practice=false,commandId=crypto.randomUUID())=>request<FlashcardReview>('/v1/flashcard-review-sessions',{method:'POST',body:JSON.stringify({commandId,deckId,practice,timezone:Intl.DateTimeFormat().resolvedOptions().timeZone})}),
 session:(id:string)=>request<FlashcardReview>(`/v1/flashcard-review-sessions/${encodeURIComponent(id)}`),
 rate:(session:FlashcardReview,body:Record<string,unknown>)=>request<FlashcardReview>(`/v1/flashcard-review-sessions/${encodeURIComponent(session.id)}/commands`,{method:'POST',body:JSON.stringify({expectedRevision:session.revision,attemptId:session.current?.attemptId,commandId:crypto.randomUUID(),...body})}),
 preferences:()=>request<{proactiveDrafts:boolean;reminders:boolean;timezone:string}>('/v1/flashcard-preferences'),
 savePreferences:(body:{proactiveDrafts:boolean;reminders:boolean;timezone:string})=>request('/v1/flashcard-preferences',{method:'PUT',body:JSON.stringify(body)}),
};

/** Resolve explicit chat requests through the same typed capability. */
export async function routeFlashcardRequest(text:string,sessionId:string,courseId?:string,refs?:FlashcardSourceRef[]):Promise<boolean>{
 if(!/^(?:please\s+)?(?:make|create|generate|prepare|build)\s+(?:me\s+)?(?:some\s+)?(?:flash\s*cards|cards\s+for\s+(?:review|study))/i.test(text.trim()))return false;
 let selected=refs;
 if(!selected?.length){const {learningApi}=await import('./api');const note=await learningApi.getStudyNote(sessionId).catch(()=>null);if(note){const value=await learningApi.getWorkspaceNote(note.noteId);selected=[{kind:'lesson',id:value.id,revision:value.revision}];}}
 const {openWorkspaceFlashcards}=await import('./workspace-events');
 if(!selected?.length){openWorkspaceFlashcards({view:'library',sessionId,courseId});return true;}
 await flashcardsApi.generate({sessionId,courseId,origin:'conversation',sourceRefs:selected,objective:text,clientCommandId:crypto.randomUUID()});
 openWorkspaceFlashcards({view:'library',sessionId,courseId,sourceRefs:selected});return true;
}
