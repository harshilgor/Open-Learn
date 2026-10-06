import { request, requestBlob, requestStream, LearningApiError, authenticatedResource, type LectureStatus, type LectureTranscriptSegment } from './api';
import { openWorkspaceSource,openWorkspaceQuiz,openWorkspaceNote,openWorkspaceFlashcards } from './workspace-events';
import type { MaterialUploadSession } from './material-upload';
export type ClassPolicy={notes:boolean;materials:boolean;practice:boolean;flashcards:boolean;noteDensity:'concise'|'standard'|'detailed';practiceCadence:'off'|'every_10_minutes'|'every_20_minutes'|'at_end';followProfessor:'off'|'explicit'|'all';showInterimTranscript:boolean;transcriptFontScale:'small'|'standard'|'large';autoScrollLock:boolean;keepAudio:boolean;buddyQuietDuringClass:boolean};
export const CLASS_POLICY_DEFAULTS:ClassPolicy={notes:true,materials:true,practice:false,flashcards:false,noteDensity:'standard',practiceCadence:'off',followProfessor:'explicit',showInterimTranscript:true,transcriptFontScale:'standard',autoScrollLock:true,keepAudio:true,buddyQuietDuringClass:false};
export function normalizeClassPolicy(policy?:Partial<ClassPolicy>,keepAudioFallback?:unknown):ClassPolicy{
  const normalized={...CLASS_POLICY_DEFAULTS,...policy};
  if(typeof keepAudioFallback==='boolean')normalized.keepAudio=keepAudioFallback;
  else if(!policy||policy.keepAudio===undefined)normalized.keepAudio=true;
  if(!policy?.practiceCadence)normalized.practiceCadence=policy?.practice?'every_10_minutes':'off';
  return normalized;
}
export type ClassReferenceGeometry={status:'measured'|'estimated'|'unavailable';pageSpace?:{coordinateSpace:string;cropBox?:number[];mediaBox?:number[];rotation?:number;renderTransform?:number[]};coordinateSpace?:string;confidence?:string;regions?:{x:number;y:number;width:number;height:number;quad?:number[][]}[]};
export type ClassPdfOutlineEntry={title:string;pageIndex:number;pageLabel:string;depth:number};
export type ClassPdfManifest={versionId:string;pageCount:number;pageLabels:string[];outline:ClassPdfOutlineEntry[];outlineStatus:'available'|'empty';ocrStatus?:'not_needed'|'complete'|'partial'|'disabled'|'no_text'|'unavailable';ocrDeferredPageCount?:number;indexProgress?:{indexVersion:number;pages:Record<string,number>;ocrWork:Record<string,number>}};
export type ClassReference={spanId:string;versionId?:string;title:string;text:string;pageIndex:number;pageLabel?:string|null;geometry?:ClassReferenceGeometry|null;extractionStatus?:string;ocrConfidence?:number|null};
export type ClassAction=
  |{type:'open-reference';source:ClassReference}
  |{type:'open-source';source:Pick<ClassReference,'spanId'|'versionId'|'title'>}
  |{type:'resolve-need';needId:string;versionId:string}
  |{type:'open-quiz';sessionId:string;quizId:string}
  |{type:'open-note';noteId:string}
  |{type:'open-flashcards';deckId:string}
  |{type:'open-media';url:string};
export class ClassActionRouter{
  constructor(private readonly showReference:(source:ClassReference)=>void,private readonly resolveNeed:(needId:string,versionId:string)=>void){}
  dispatch(action:ClassAction):boolean{
    switch(action.type){
      case 'open-reference':this.showReference(action.source);return true;
      case 'open-source':openWorkspaceSource(action.source);return true;
      case 'resolve-need':this.resolveNeed(action.needId,action.versionId);return true;
      case 'open-quiz':openWorkspaceQuiz({sessionId:action.sessionId,origin:'ask',quizId:action.quizId});return true;
      case 'open-note':openWorkspaceNote(action.noteId);return true;
      case 'open-flashcards':openWorkspaceFlashcards({deckId:action.deckId,view:'editor'});return true;
      case 'open-media':{
        try{const url=new URL(action.url,window.location.href);if(!['http:','https:'].includes(url.protocol))return false;window.open(url.toString(),'_blank','noopener,noreferrer');return true;}catch{return false;}
      }
    }
    return false;
  }
}
export type ClassSetup={deviceId:string;captureCapability?:string;materialVersionIds:string[];policy:ClassPolicy};
export type ClassNoteSourceManifest={recordingId:string;startMs:number;endMs:number;sourceRevision:string;reconciliationId:string;segments:{segmentId:string;startMs:number;endMs:number;revision:number}[];contextSegments?:{segmentId:string;startMs:number;endMs:number;revision:number}[]};
export type ClassOutput={id:string;windowId:string;windowStartMs?:number;kind:string;status:string;revision:number;error?:string;provisional?:boolean;settlement?:'provisional'|'settled'|'partial';sourceManifest?:ClassNoteSourceManifest|null;reconciles?:string[];result?:{blocks?:{title:string;body:string;segmentIds:string[];sourceManifest?:ClassNoteSourceManifest;reconciliationId?:string}[];items?:{prompt:string;answer:string;segmentIds:string[]}[];sources?:ClassReference[];quizId?:string;deckId?:string;boundedCoverage?:boolean;evidenceMode?:'hierarchical';sourceWindowCount?:number}};
export type ClassNeedInfo={id:string;windowId:string;kind:string;status:'open'|'provided'|'dismissed';prompt:string;query:string;versionId?:string};
export type ClassNeedPage={items:ClassNeedInfo[];hasMore:boolean;nextCursor:string|null};
export type ResourceConnectorId='library'|'upload'|'url'|'drive'|'canvas'|'blackboard'|'moodle';
export type ResourceMediaType='application/pdf'|'text/plain'|'text/markdown';
export type ClassResourceConnector={id:ResourceConnectorId;name:string;status:'supported'|'stub';capabilities:('select'|'read'|'import')[];requiredFields:string[];options:{name:string;required:boolean;option:string;maxLength?:number|null}[];requiresConnection:boolean;externalWritesEnabled:false;detail:string};
export type CourseResourcePreferences={connectorOrder:ResourceConnectorId[];enabledConnectors:ResourceConnectorId[];allowPublicUrls:boolean;acceptedMediaTypes:ResourceMediaType[];maxUploadBytes:number;requireExplicitSelection:true;crossCourseLibrarySearch:false};
export type CourseResourcePreferencesSnapshot={courseId:string|null;revision:number;preferences:CourseResourcePreferences;updatedAt:number|null};
export type ClassResourceIntent={id:string;classId:string;needId:string;courseId:string|null;windowId:string;kind:string;prompt:string;query:string;requiredFields:string[];options:Record<string,unknown>;status:'open'|'resolving'|'resolved'|'closed';selectedConnector:ResourceConnectorId|null;selectedResource:Record<string,unknown>|null;materialVersionId:string|null;lastError:string|null;createdAt:number;updatedAt:number};
export type ClassMaterialOption={versionId:string;title:string;status:string;role:string};
export type ClassMaterialIntake={intakeId:string;classId:string;needId:string;commandId:string;sourceKind:'url'|'upload'|'drive'|'canvas';status:'queued'|'fetching'|'awaiting_upload'|'uploading'|'processing'|'attached'|'failed';materialId?:string|null;versionId?:string|null;uploadPath?:string;resumableUploadPath?:string;url?:string|null;error?:string|null};
export type ClassMaterialIntakeSource={sourceKind:'url';url:string}|{sourceKind:'upload';title:string;mediaType:'application/pdf'|'text/plain'|'text/markdown';byteCount:number}|{sourceKind:'drive';connectionId:string;fileId:string}|{sourceKind:'canvas';connectionId:string;entityId:string};
export type ClassMaterialIntakeCreate=ClassMaterialIntakeSource&{expectedRevision:number;commandId:string};
export type ClassDriveConnection={id:string;status:string;email?:string;capabilities:string[]};
export type ClassDriveFile={id:string;name:string;mimeType:string;size?:string;modifiedTime?:string};
export type ClassCanvasSource={entityId:string;connectionId:string;title:string;preview:string;sourceRevision:string;lastSuccessfulSync?:number|null};
export type ClassMetrics={classId:string;retainedSampleLimit:number;stages:Record<string,{sampleCount:number;outcomes:Record<string,number>;queueWaitP50Ms:number|null;queueWaitP90Ms:number|null;runP50Ms:number|null;runP90Ms:number|null;endToEndP50Ms:number|null;endToEndP90Ms:number|null;lastFinishedAt:number;counters:Record<string,number>;lastCounters:Record<string,number>}>};
export type ClassProvisionalNote={id:string;liveSegmentId:string;revision:number;sourceVersion:number;status:string;startMs:number;endMs:number;result:{blocks?:{title:string;body:string;segmentIds:string[]}[]};authoritativeSources:{segmentId:string;revision:number}[];error?:string|null;createdAt:number};
export type ClassLibraryCue={kind:'physical_page'|'page_label'|'chapter'|'section'|'slide'|'figure'|'equation';value:string};
export type ClassReferenceLookup={candidates:ClassReference[];ambiguous:boolean;hasMore:boolean;indexVersion:number};
export type ClassSnapshot={provisionalNotes?:ClassProvisionalNote[];interimTranscript?:{id:string;text:string;revision:number;expiresAt:number}[];session:{id:string;revision:number;recordingId:string;sessionId:string;noteId:string;buddyId:string;courseId:string|null;title:string;processing:string;cancelled:boolean;partial:boolean;policy?:Partial<ClassPolicy>;needInfo?:ClassNeedInfo[];needInfoHasMore?:boolean;needInfoNextCursor?:string|null;activeWindows?:string[];packageWindow?:string;sourceCorrected?:boolean;noSpeech?:boolean;watermark?:number;outputTransitionPending?:boolean;materialAccessRevision?:number};recording:LectureStatus;outputs:ClassOutput[];outputHasMore?:boolean;outputCursor?:string|null;outputGeneration?:number;outputPatchIds?:string[];transcript:LectureTranscriptSegment[];liveTranscript:ClassLiveTranscriptSegment[];liveTranscriptReset?:boolean;transcriptHasMore?:boolean|null;transcriptCursor?:string|null;transcriptGeneration?:number;cursor:number;hasMore:boolean;events:{id:string;cursor:number;type:string;data:unknown}[];delta?:boolean;transcriptReset?:boolean;outputsReset?:boolean};
export type ClassTranscriptPage={items:LectureTranscriptSegment[];hasMore:boolean;nextCursor:string|null;generation:number};
export type ClassOutputPage={items:ClassOutput[];hasMore:boolean;nextCursor:string|null;generation:number};
export type ClassLiveTranscriptSegment={id:string;streamId:string;streamSequence:number;providerItemId:string;text:string;transcriptionVersion:number;startMs?:number|null;endMs?:number|null;createdAt:number};
async function streamClassSnapshots(id:string,cursor:number,lastEventId:string|undefined,signal:AbortSignal,onSnapshot:(snapshot:ClassSnapshot,eventId?:string)=>void):Promise<void>{
  const headers=new Headers({'Accept':'text/event-stream'});if(lastEventId)headers.set('Last-Event-ID',lastEventId);
  const response=await requestStream(`/v1/class-sessions/${encodeURIComponent(id)}/stream?cursor=${cursor}&initialized=true`,{headers,signal});
  if(!response.body)throw new LearningApiError(503,'stream_unavailable','The class event stream is unavailable.');
  const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='';
  const consume=(frame:string)=>{let event='message',frameId:string|undefined;const data:string[]=[];for(const line of frame.split('\n')){if(!line||line.startsWith(':'))continue;const separator=line.indexOf(':');const field=separator<0?line:line.slice(0,separator);const value=separator<0?'':line.slice(separator+1).replace(/^ /,'');if(field==='event')event=value;else if(field==='id'&&!value.includes('\0'))frameId=value;else if(field==='data')data.push(value);}if(event!=='class.snapshot'||!data.length)return;try{onSnapshot(JSON.parse(data.join('\n')) as ClassSnapshot,frameId);}catch{throw new LearningApiError(502,'invalid_stream_event','The class event stream returned invalid data.');}};
  try{while(true){const {done,value}=await reader.read();if(done)break;buffer+=decoder.decode(value,{stream:true}).replace(/\r\n/g,'\n');let boundary=buffer.indexOf('\n\n');while(boundary>=0){consume(buffer.slice(0,boundary));buffer=buffer.slice(boundary+2);boundary=buffer.indexOf('\n\n');}}buffer+=decoder.decode();if(buffer.trim())consume(buffer.replace(/\r\n/g,'\n'));}
  finally{reader.releaseLock();}
}
export function mergeClassSnapshot(current:ClassSnapshot|null,next:ClassSnapshot):ClassSnapshot{
  if(!next.delta||!current||current.session.id!==next.session.id)return next;
  const outputMap=new Map<string,ClassOutput>(next.outputsReset?[]:current.outputs.map(output=>[output.id,output] as const));
  const patchIds=new Set(next.outputsReset?[]:(next.outputPatchIds??[]));
  for(const output of next.outputs){const previous=outputMap.get(output.id);if(patchIds.has(output.id)&&!previous)continue;if(!previous||output.revision>=previous.revision)outputMap.set(output.id,output);}
  const transcriptMap=new Map<string,LectureTranscriptSegment>(next.transcriptReset?[]:current.transcript.map(segment=>[segment.id,segment] as const));
  for(const segment of next.transcript)transcriptMap.set(segment.id,segment);
  const eventMap=new Map<string,ClassSnapshot['events'][number]>(current.events.map(event=>[event.id,event] as const));
  for(const event of next.events)eventMap.set(event.id,event);
  const transcript=[...transcriptMap.values()].sort((a,b)=>a.startMs-b.startMs||a.id.localeCompare(b.id));
  const liveTranscriptMap=new Map<string,ClassLiveTranscriptSegment>((next.liveTranscriptReset?next.liveTranscript:(current.liveTranscript??[])).map(segment=>[segment.id,segment] as const));
  for(const event of next.events){if(event.type!=='transcript.live_final')continue;const segment=(event.data as {liveSegment?:ClassLiveTranscriptSegment}|null)?.liveSegment;if(segment?.id)liveTranscriptMap.set(segment.id,segment);}
  const liveTranscript=[...liveTranscriptMap.values()].sort((a,b)=>a.createdAt-b.createdAt||a.id.localeCompare(b.id)).slice(-100);
  const events=[...eventMap.values()].slice(-200);
  const outputs=[...outputMap.values()].sort((a,b)=>(a.windowStartMs??0)-(b.windowStartMs??0)||a.kind.localeCompare(b.kind)||a.id.localeCompare(b.id));
  return {...next,outputs,transcript,liveTranscript,events,outputHasMore:next.outputsReset?next.outputHasMore:current.outputHasMore,outputCursor:next.outputsReset?next.outputCursor:current.outputCursor,outputGeneration:next.outputsReset?next.outputGeneration:current.outputGeneration,transcriptHasMore:next.transcriptReset?next.transcriptHasMore:current.transcriptHasMore,transcriptCursor:next.transcriptReset?next.transcriptCursor:current.transcriptCursor,transcriptGeneration:next.transcriptReset?next.transcriptGeneration:current.transcriptGeneration};
}
export const CLASS_OPEN_EVENT='openlearn-class-open';
export const CLASS_CHAT_OPEN_REQUEST_EVENT='openlearn-class-chat-open-request';
export type ClassChatOpenResult={title:string;pageIndex:number};
export type ClassReferenceCue={kind:'chapter'|'figure';number:number};
export type ClassReferenceOpenIntent={query:string;pageNumber:number|null;cue?:ClassReferenceCue|null;libraryCue?:ClassLibraryCue|null};
export type ClassChatOpenRequestDetail={classId:string;chatSessionId:string;query:string;pageNumber:number|null;cue?:ClassReferenceCue|null;libraryCue?:ClassLibraryCue|null;pending?:Promise<ClassChatOpenResult|null>;result:ClassChatOpenResult|null};
let activeClassId:string|null=null;
export function setActiveClassContext(classId:string|null){activeClassId=classId;}
export function openClassWorkspace(classId:string,sessionId?:string){activeClassId=classId;window.dispatchEvent(new CustomEvent(CLASS_OPEN_EVENT,{detail:{classId,sessionId}}));}
function normalizedReferenceCue(value:string):{cue:ClassLibraryCue;matched:string}|null{
  const printed=value.match(/\b(?:printed\s+page|page\s+label)\s+([a-z0-9.-]+)\b/i);
  if(printed)return {cue:{kind:'page_label',value:printed[1]},matched:printed[0]};
  const match=value.match(/\b(physical\s+page|page|slide|chapter|ch\.?|section|sec\.?|figure|fig\.?|equation|eq\.?)\s*([0-9]+(?:[.-][0-9]+)*[a-z]?)\b/i);
  if(!match)return null;
  const prefix=match[1].toLowerCase();
  const kind:ClassLibraryCue['kind']=prefix.includes('page')?'physical_page':prefix==='slide'?'slide':prefix.startsWith('ch')?'chapter':prefix.startsWith('sec')?'section':prefix.startsWith('fig')?'figure':'equation';
  return {cue:{kind,value:match[2]},matched:match[0]};
}
export function parseClassReferenceOpenRequest(message:string):ClassReferenceOpenIntent|null{
  const cleaned=message.trim().replace(/\s+/g,' ');
  const actionMatch=cleaned.match(/^(?:please\s+)?(?:(?:can|could)\s+you\s+)?(?:open|pull\s+up|show\s+me|bring\s+up)\s+(?:the\s+)?(.+?)[.!?]*$/i);
  if(actionMatch){
    const normalized=normalizedReferenceCue(actionMatch[1]);
    if(normalized){
      const query=actionMatch[1].replace(normalized.matched,' ').replace(/^[\s]*(?:about|on|for|from|in|of)\s+/i,'').replace(/\s+/g,' ').trim();
      if(query.length<=200&&!/https?:\/\//i.test(query))return {query,pageNumber:normalized.cue.kind==='physical_page'?Number(normalized.cue.value):null,libraryCue:normalized.cue};
    }
    let query=actionMatch[1].trim().replace(/[.!?]+$/,'').trim();
    const cueMatch=/^(?:how|why|what|when|where|who|explain|describe|tell me)\b/i.test(query)?null:query.match(/\b(chapter|chapters|ch\.?|figure|figures|fig\.?)\s*(\d+)\b/i);
    if(cueMatch){
      const kind=/^(?:chapter|chapters|ch\.?$)/i.test(cueMatch[1])?'chapter':'figure';
      const number=Number(cueMatch[2]);
      if(Number.isSafeInteger(number)&&number>0){
        query=query.replace(cueMatch[0],' ').replace(/\s+/g,' ').trim();
        query=query.replace(/^(?:about|on|for|from|in|of|titled|called)\s+/i,'').trim();
        if(query.length<=200&&!/https?:\/\//i.test(query))return {query,pageNumber:null,cue:{kind,number}};
      }
    }
  }
  const match=message.trim().replace(/\s+/g,' ').match(/^(?:please\s+)?(?:(?:can|could)\s+you\s+)?(open|pull\s+up|show\s+me|bring\s+up)\s+(?:the\s+)?(?:(source|slides?|pages?|passages?|sections?|references?|materials?)\s*)?(.+?)[.!?]*$/i);
  if(!match)return null;
  const action=match[1].toLowerCase();
  const cue=match[2]?.toLowerCase()||'';
  let query=match[3].trim().replace(/[.!?]+$/,'').trim();
  if(action==='show me'&&!cue||/^(?:how|why|what|when|where|who|explain|describe|tell me)\b/i.test(query))return null;
  let pageNumber:number|null=null;
  const explicitPage=query.match(/\bpage\s+(\d+)\b/i);
  const numberedPage=query.match(/^(\d+)(?:\s+(?:about|on|for|from|in|of)\s+(.+))?$/i);
  if(explicitPage){pageNumber=Number(explicitPage[1]);query=query.replace(/\bpage\s+\d+\b/i,' ').trim();}
  else if(/^(?:page|pages|slide|slides)$/.test(cue)&&numberedPage){pageNumber=Number(numberedPage[1]);query=numberedPage[2]||'';}
  query=query.replace(/^(?:about|on|for|from|in|of)\s+/i,'').trim();
  if((!query&&pageNumber===null)||query.length>200||/https?:\/\//i.test(query))return null;
  return {query,pageNumber};
}
export function parseProfessorReferenceCue(message:string,followAll:boolean):ClassReferenceOpenIntent|null{
  const cleaned=message.trim().replace(/\s+/g,' ');
  const normalized=normalizedReferenceCue(cleaned);
  if(normalized)return {query:'',pageNumber:normalized.cue.kind==='physical_page'?Number(normalized.cue.value):null,libraryCue:normalized.cue};
  const page=cleaned.match(/\b(?:page|slide)\s+(\d+)\b/i);
  if(page){const pageNumber=Number(page[1]);return Number.isSafeInteger(pageNumber)&&pageNumber>0?{query:'',pageNumber}:null;}
  const chapter=cleaned.match(/\b(?:chapter|ch\.?)\s*(\d+)\b/i);
  if(chapter){const number=Number(chapter[1]);return Number.isSafeInteger(number)&&number>0?{query:'',pageNumber:null,cue:{kind:'chapter',number}}:null;}
  const figure=cleaned.match(/\b(?:figure|fig\.?)\s*(\d+)\b/i);
  if(figure){const number=Number(figure[1]);return Number.isSafeInteger(number)&&number>0?{query:'',pageNumber:null,cue:{kind:'figure',number}}:null;}
  return followAll&&cleaned.length>=20?{query:cleaned,pageNumber:null}:null;
}
export async function requestClassReferenceOpen(intent:ClassReferenceOpenIntent,chatSessionId:string|null):Promise<ClassChatOpenResult|null>{
  if(typeof window==='undefined'||!activeClassId||!chatSessionId)return null;
  const detail:ClassChatOpenRequestDetail={classId:activeClassId,chatSessionId,query:intent.query,pageNumber:intent.pageNumber,cue:intent.cue??null,libraryCue:intent.libraryCue??null,result:null};
  window.dispatchEvent(new CustomEvent<ClassChatOpenRequestDetail>(CLASS_CHAT_OPEN_REQUEST_EVENT,{detail}));
  return detail.pending?await detail.pending:detail.result;
}
export function findClassReference(sources:ClassReference[],query:string,pageNumber:number|null=null,cue:ClassReferenceCue|null=null):ClassReference|null{
  const unique=[...new Map(sources.map(source=>[source.spanId,source])).values()];
  const residual=query.trim();
  const ignored=new Set(['a','an','and','about','bring','by','can','chapter','class','course','for','from','in','lecture','me','my','note','notes','of','on','open','page','passage','reference','section','show','slide','source','the','to','up','you']);
  const terms=[...new Set(residual.toLowerCase().match(/[a-z0-9]{3,}/g)||[])].filter(term=>!ignored.has(term));
  if(pageNumber===null&&!cue&&!terms.length)return null;
  const ranked=unique.map(source=>{
    const title=source.title.toLowerCase();
    const text=source.text.toLowerCase();
    const haystack=`${title} ${text}`;
    let score=pageNumber!==null&&source.pageIndex+1===pageNumber?8:0;
    const cuePattern=cue?cue.kind==='chapter'?new RegExp(`\\b(?:chapter|ch\\.?)\\s*0*${cue.number}\\b`,'i'):new RegExp(`\\b(?:figure|fig\\.?)\\s*0*${cue.number}\\b`,'i'):null;
    const cueMatch=!!cuePattern&&cuePattern.test(haystack);
    if(cueMatch)score+=10;
    const phrase=residual.toLowerCase();
    if(phrase.length>=5&&(title.includes(phrase)||text.includes(phrase)))score+=8;
    for(const term of terms){if(title.includes(term))score+=3;else if(text.includes(term))score+=1;}
    const contentMatches=cue?cueMatch&&(terms.length===0||terms.some(term=>haystack.includes(term))):terms.length?terms.some(term=>haystack.includes(term)):pageNumber!==null;
    return {source,score,eligible:(pageNumber===null||source.pageIndex+1===pageNumber)&&contentMatches};
  }).filter(item=>item.eligible&&item.score>=3).sort((a,b)=>b.score-a.score);
  if(!ranked.length||ranked.length>1&&ranked[0].score===ranked[1].score)return null;
  return ranked[0].source;
}
export const classApi={
  retryProvisionalNote:(id:string,noteId:string,revision:number)=>request<ClassSnapshot>(`/v1/class-sessions/${encodeURIComponent(id)}/provisional-notes/${encodeURIComponent(noteId)}/retry?revision=${revision}`,{method:"POST"}),
  needs:(id:string,cursor:string)=>request<ClassNeedPage>(`/v1/class-sessions/${encodeURIComponent(id)}/needs?cursor=${encodeURIComponent(cursor)}`),
  lookupReference:(id:string,query:string,cue?:{kind:string;value:string}|null)=>{const params=new URLSearchParams({query});if(cue){params.set('kind',cue.kind);params.set('value',cue.value);}return request<ClassReferenceLookup>(`/v1/class-sessions/${encodeURIComponent(id)}/reference-lookup?${params.toString()}`);},
  snapshot:(id:string,cursor=0,initialized=false)=>request<ClassSnapshot>(`/v1/class-sessions/${encodeURIComponent(id)}?cursor=${cursor}&initialized=${initialized}`),
  events:(id:string,cursor=0,initialized=true,lastEventId?:string)=>request<ClassSnapshot>(`/v1/class-sessions/${encodeURIComponent(id)}/events?cursor=${cursor}&initialized=${initialized}`,{headers:lastEventId?{'Last-Event-ID':lastEventId}:undefined}),
  stream:(id:string,cursor:number,lastEventId:string|undefined,signal:AbortSignal,onSnapshot:(snapshot:ClassSnapshot,eventId?:string)=>void)=>streamClassSnapshots(id,cursor,lastEventId,signal,onSnapshot),
  outputsPage:(id:string,cursor:string)=>request<ClassOutputPage>(`/v1/class-sessions/${encodeURIComponent(id)}/outputs?cursor=${encodeURIComponent(cursor)}`),
  transcriptPage:(id:string,cursor:string)=>request<ClassTranscriptPage>(`/v1/class-sessions/${encodeURIComponent(id)}/transcript?cursor=${encodeURIComponent(cursor)}`),
  transcriptSegments:(id:string,segmentIds:string[])=>{const query=new URLSearchParams();for(const segmentId of [...new Set(segmentIds)].slice(0,100))query.append('segmentId',segmentId);return request<ClassTranscriptPage>(`/v1/class-sessions/${encodeURIComponent(id)}/transcript?${query.toString()}`);},
  metrics:(id:string)=>request<ClassMetrics>(`/v1/class-sessions/${encodeURIComponent(id)}/metrics`),
  materials:(courseId:string|null)=>request<{materials:ClassMaterialOption[]}>(`/v1/materials${courseId?`?course_id=${encodeURIComponent(courseId)}`:''}`),
  driveConnections:()=>request<{items:ClassDriveConnection[];enabled:boolean}>('/v1/assistant/app-connections'),
  driveSources:(connectionId:string,pageToken?:string)=>request<{data:{files?:ClassDriveFile[];nextPageToken?:string};classification:string}>(`/v1/assistant/app-connections/${encodeURIComponent(connectionId)}/sources?kind=drive${pageToken?`&pageToken=${encodeURIComponent(pageToken)}`:''}`),
  canvasSources:(id:string)=>request<{items:ClassCanvasSource[]}>(`/v1/class-sessions/${encodeURIComponent(id)}/canvas-sources`),
  resourceConnectors:(id:string)=>request<{items:ClassResourceConnector[];externalWritesEnabled:false}>(`/v1/class-sessions/${encodeURIComponent(id)}/resource-connectors`),
  resourceIntents:(id:string)=>request<{items:ClassResourceIntent[];courseId:string|null;preferences:CourseResourcePreferencesSnapshot;connectors:ClassResourceConnector[]}>(`/v1/class-sessions/${encodeURIComponent(id)}/resource-intents`),
  resourcePreferences:(id:string)=>request<CourseResourcePreferencesSnapshot>(`/v1/class-sessions/${encodeURIComponent(id)}/resource-preferences`),
  updateResourcePreferences:(id:string,expectedRevision:number,preferences:CourseResourcePreferences)=>request<CourseResourcePreferencesSnapshot>(`/v1/class-sessions/${encodeURIComponent(id)}/resource-preferences`,{method:'PUT',body:JSON.stringify({...preferences,expectedRevision})}),
  startMaterialIntake:(id:string,needId:string,body:ClassMaterialIntakeCreate)=>request<ClassMaterialIntake>(`/v1/class-sessions/${encodeURIComponent(id)}/needs/${encodeURIComponent(needId)}/intakes`,{method:'POST',body:JSON.stringify(body)}),
  materialIntakes:(id:string,needId?:string)=>request<{intakes:ClassMaterialIntake[]}>(`/v1/class-sessions/${encodeURIComponent(id)}/material-intakes${needId?`?needId=${encodeURIComponent(needId)}`:''}`),
  referencePdf:(id:string,versionId:string,signal?:AbortSignal)=>requestBlob(`/v1/class-sessions/${encodeURIComponent(id)}/materials/${encodeURIComponent(versionId)}/file`,signal),
  referencePdfSource:(id:string,versionId:string)=>authenticatedResource(`/v1/class-sessions/${encodeURIComponent(id)}/materials/${encodeURIComponent(versionId)}/file`),
  referencePdfManifest:(id:string,versionId:string,signal?:AbortSignal)=>request<ClassPdfManifest>(`/v1/class-sessions/${encodeURIComponent(id)}/materials/${encodeURIComponent(versionId)}/manifest`,{signal}),
  uploadMaterialIntake:(uploadPath:string,file:Blob,mediaType:string)=>request<ClassMaterialIntake>(uploadPath,{method:'PUT',headers:{'Content-Type':mediaType},body:file}),
  startMaterialUpload:(path:string)=>request<MaterialUploadSession>(path,{method:'POST'}),
  uploadMaterialPart:(sessionUrl:string,index:number,part:Blob)=>request(`${sessionUrl}/parts/${index}`,{method:'PUT',headers:{'Content-Type':'application/octet-stream'},body:part}),
  completeMaterialUpload:(sessionUrl:string)=>request<ClassMaterialIntake>(`${sessionUrl}/complete`,{method:'POST'}),
  attachMaterial:(id:string,expectedRevision:number,needId:string,versionId:string)=>request<ClassSnapshot>(`/v1/class-sessions/${encodeURIComponent(id)}/materials`,{method:'POST',body:JSON.stringify({expectedRevision,needId,versionId})}),
  create:(recording:Record<string,unknown>,setup:ClassSetup)=>request<ClassSnapshot>('/v1/class-sessions',{method:'POST',body:JSON.stringify({recording,...setup})}),
  command:(id:string,expectedRevision:number,action:string,outputId?:string,policy?:ClassPolicy)=>request<ClassSnapshot>(`/v1/class-sessions/${encodeURIComponent(id)}/commands`,{method:'POST',body:JSON.stringify({expectedRevision,action,outputId,policy})}),
};
