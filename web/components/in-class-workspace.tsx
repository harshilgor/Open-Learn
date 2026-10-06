"use client";
import { useCallback,useEffect,useMemo,useRef,useState } from 'react';
import { classApi,mergeClassSnapshot,ClassActionRouter,CLASS_CHAT_OPEN_REQUEST_EVENT,findClassReference,parseProfessorReferenceCue,normalizeClassPolicy,type ClassChatOpenRequestDetail,type ClassSnapshot,type ClassOutput,type ClassPolicy,type ClassReference,type ClassPdfManifest,type ClassMaterialOption,type ClassMaterialIntake,type ClassMaterialIntakeCreate,type ClassMaterialIntakeSource,type ClassDriveConnection,type ClassDriveFile,type ClassCanvasSource,type ClassMetrics,type ClassResourceConnector,type ResourceConnectorId,type CourseResourcePreferences,type CourseResourcePreferencesSnapshot,type ResourceMediaType } from '@/lib/in-class';
import {useBuddies,BuddyAvatar} from './buddies';
import {RichContent} from './rich-content';
import {Button} from './ui/button';
import styles from './in-class-workspace.module.css';
import { LIVE_LECTURE_TRANSCRIPTION_EVENT, type LiveTranscriptionDetail } from '@/lib/live-lecture-transcription';
import { ACCOUNT_CHANGED } from '@/lib/account-session';
import { uploadMaterialParts } from '@/lib/material-upload';
import {ClassPdfReader} from './class-pdf-reader';
import {ClassYoutubeSearch} from './class-youtube-search';
import {LearningApiError} from '@/lib/api';

const mergeSnapshot=(current:ClassSnapshot|null,next:ClassSnapshot)=>typeof mergeClassSnapshot==='function'?mergeClassSnapshot(current,next):next;
const ACTIVE_INTAKE_STATUSES=new Set(['queued','fetching','uploading','processing']);
const TERMINAL_INTAKE_STATUSES=new Set(['attached','failed']);
const MEBIBYTE=1024*1024;
const MAX_CLASS_UPLOAD_MIB=500;
const DRIVE_MAX_BYTES=5_000_000;
const intakeProgress:Record<ClassMaterialIntake['status'],number>={awaiting_upload:0,queued:0,fetching:1,uploading:2,processing:3,attached:4,failed:4};
function mergeIntakes(current:ClassMaterialIntake[],incoming:ClassMaterialIntake[]){const byId=new Map(current.map(item=>[item.intakeId,item]));const seen=new Set<string>();const merged=incoming.map(item=>{seen.add(item.intakeId);const previous=byId.get(item.intakeId);const result=previous&&intakeProgress[previous.status]>intakeProgress[item.status]?previous:item;byId.set(item.intakeId,result);return result;});return [...merged,...current.filter(item=>!seen.has(item.intakeId))];}
function formatCueTime(milliseconds:number){const totalSeconds=Math.max(0,Math.floor(milliseconds/1000));return `${Math.floor(totalSeconds/60)}:${String(totalSeconds%60).padStart(2,'0')}`;}
function formatMebibytes(bytes:number){return String(Number((bytes/MEBIBYTE).toFixed(6)));}
function transcriptionStatus(snapshot:ClassSnapshot){
  const {recording,session}=snapshot;const chunks=recording.chunks;const confirmed=chunks.serverConfirmed??0;const transcribed=chunks.transcribed??0;const pending=Math.max(0,confirmed-transcribed);const expected=chunks.expected;const awaitingUpload=recording.captureComplete&&typeof expected==='number'?Math.max(0,expected-confirmed):0;
  if(recording.captureInterrupted||chunks.failed>0||chunks.missing.length>0)return {state:'recovery',label:'Recovery needed',detail:[chunks.failed?`${chunks.failed} failed`:null,chunks.missing.length?`${chunks.missing.length} missing`:null,recording.captureInterrupted?'capture was interrupted':null].filter(Boolean).join(' · ')||'Some audio may need recovery.'};
  if(awaitingUpload>0)return {state:'uploading',label:'Waiting for audio upload',detail:`${awaitingUpload} expected ${awaitingUpload===1?'slice':'slices'} not confirmed by the server yet.`};
  if(pending>0)return {state:'transcribing',label:'Transcription catching up',detail:`${pending} uploaded ${pending===1?'slice is':'slices are'} still being transcribed.`};
  const coordinated=typeof session.watermark==='number'?Math.max(0,Math.floor(session.watermark)+1):transcribed;const notesPending=Math.max(0,transcribed-coordinated);
  if(notesPending>0)return {state:'coordinating',label:'Transcript ready · notes catching up',detail:`${notesPending} transcribed ${notesPending===1?'slice is':'slices are'} still moving into class notes.`};
  if(recording.captureComplete)return {state:'caught-up',label:'Transcript caught up',detail:`${transcribed} audio ${transcribed===1?'slice':'slices'} transcribed.`};
  return {state:'recording',label:'Transcript current for uploaded audio',detail:`${transcribed} audio ${transcribed===1?'slice':'slices'} transcribed. Capture is active, so newer speech may not be uploaded yet.`};
}
async function stableIntakeCommandId(classId:string,needId:string,source:string){const digest=new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(source)));const fingerprint=Array.from(digest,byte=>byte.toString(16).padStart(2,'0')).join('');const key=`openlearn.class-intake-command:${encodeURIComponent(classId)}:${encodeURIComponent(needId)}:${fingerprint}`;const saved=localStorage.getItem(key);if(saved)return {commandId:saved,key};const commandId=crypto.randomUUID().replaceAll('-','');localStorage.setItem(key,commandId);return {commandId,key};}
async function fingerprintFile(file:File){const chunks:string[]=[];const chunkBytes=1024*1024;for(let offset=0;offset<file.size;offset+=chunkBytes){const digest=new Uint8Array(await crypto.subtle.digest('SHA-256',await file.slice(offset,Math.min(file.size,offset+chunkBytes)).arrayBuffer()));chunks.push(Array.from(digest,byte=>byte.toString(16).padStart(2,'0')).join(''));}const final=new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(chunks.join(':'))));return Array.from(final,byte=>byte.toString(16).padStart(2,'0')).join('');}
function forgetIntakeCommand(commandId:string){for(let index=localStorage.length-1;index>=0;index--){const key=localStorage.key(index);if(key?.startsWith('openlearn.class-intake-command:')&&localStorage.getItem(key)===commandId)localStorage.removeItem(key);}}

export function InClassWorkspace({classId}:{classId:string|null}){
  const buddies=useBuddies();
  const activeClassIdRef=useRef(classId);activeClassIdRef.current=classId;
  const [identityRevision,setIdentityRevision]=useState(0);
  const [snapshot,setSnapshot]=useState<ClassSnapshot|null>(null);
  const [liveCaptions,setLiveCaptions]=useState<LiveTranscriptionDetail|null>(null);
  const [classMetrics,setClassMetrics]=useState<ClassMetrics|null>(null);const [classMetricsBusy,setClassMetricsBusy]=useState(false);const [classMetricsError,setClassMetricsError]=useState('');
  const [view,setView]=useState('notes');const [error,setError]=useState('');
  const [followStatus,setFollowStatus]=useState('');
  const [cueStatus,setCueStatus]=useState('');const [pendingCueNavigation,setPendingCueNavigation]=useState<string|null>(null);const cueNavigationPending=useRef(false);
  const [policyUpdating,setPolicyUpdating]=useState(false);
  const [referenceState,setReferenceState]=useState<{classId:string|null;source:ClassReference}|null>(null);const reference=referenceState?.classId===classId?referenceState.source:null;const [referenceOpen,setReferenceOpen]=useState(false);
  const [referencePdfSource,setReferencePdfSource]=useState<{classId:string;versionId:string;url:string;httpHeaders:Record<string,string>}|null>(null);const [referencePdfState,setReferencePdfState]=useState<'idle'|'loading'|'ready'|'unavailable'>('idle');
  const [referenceManifest,setReferenceManifest]=useState<ClassPdfManifest|null>(null);const [referencePageIndex,setReferencePageIndex]=useState<number|null>(null);
  const referenceRequestEpoch=useRef(0);
  const libraryLookupEpoch=useRef(0);
  const referenceOpener=useRef<HTMLElement|null>(null);
  const [libraryQuery,setLibraryQuery]=useState('');
  const [libraryCueKind,setLibraryCueKind]=useState('');
  const [libraryCueValue,setLibraryCueValue]=useState('');
  const [libraryCandidates,setLibraryCandidates]=useState<ClassReference[]>([]);
  const [libraryBusy,setLibraryBusy]=useState(false);
  const [libraryStatus,setLibraryStatus]=useState('');
  const [needsPageBusy,setNeedsPageBusy]=useState(false);
  const materialAccessRevision=useRef<number|null>(null);
  const [availableMaterials,setAvailableMaterials]=useState<ClassMaterialOption[]>([]);const [materialsLoading,setMaterialsLoading]=useState(false);const [materialBusy,setMaterialBusy]=useState('');
  const [materialIntakes,setMaterialIntakes]=useState<ClassMaterialIntake[]>([]);const [intakeBusy,setIntakeBusy]=useState('');const [intakeErrors,setIntakeErrors]=useState<Record<string,string>>({});const [needUrls,setNeedUrls]=useState<Record<string,string>>({});
  const [resourceConnectors,setResourceConnectors]=useState<ClassResourceConnector[]>([]);const [resourceConnectorsScope,setResourceConnectorsScope]=useState('');
  const [resourcePreferenceState,setResourcePreferenceState]=useState<{scope:string;snapshot:CourseResourcePreferencesSnapshot}|null>(null);const [resourcePreferenceDraft,setResourcePreferenceDraft]=useState<CourseResourcePreferences|null>(null);const [resourcePreferenceScope,setResourcePreferenceScope]=useState('');const [resourcePreferenceError,setResourcePreferenceError]=useState('');const [resourcePreferenceBusy,setResourcePreferenceBusy]=useState(false);const [resourcePreferenceLoading,setResourcePreferenceLoading]=useState(false);const [resourcePreferenceReload,setResourcePreferenceReload]=useState(0);const [maxUploadMibText,setMaxUploadMibText]=useState('250');
  const [uploadProgress,setUploadProgress]=useState<Record<string,number>>({});
  const [driveConnections,setDriveConnections]=useState<ClassDriveConnection[]>([]);const [driveConnectionsLoaded,setDriveConnectionsLoaded]=useState(false);const [driveConnectionId,setDriveConnectionId]=useState('');const [driveFiles,setDriveFiles]=useState<ClassDriveFile[]>([]);const [driveNextPage,setDriveNextPage]=useState('');const [driveBusy,setDriveBusy]=useState('');const [driveError,setDriveError]=useState('');const driveLoadEpoch=useRef(0);
  const [canvasSources,setCanvasSources]=useState<ClassCanvasSource[]>([]);const [canvasSourcesLoaded,setCanvasSourcesLoaded]=useState(false);const [canvasBusy,setCanvasBusy]=useState('');const [canvasError,setCanvasError]=useState('');const canvasLoadEpoch=useRef(0);
  const [canvasSourcesClassId,setCanvasSourcesClassId]=useState('');
  const [revealed,setRevealed]=useState<Record<string,boolean>>({});
  const [citationSegments,setCitationSegments]=useState<Record<string,ClassSnapshot['transcript'][number]>>({});
  const [citationBusy,setCitationBusy]=useState<Record<string,boolean>>({});
  const [transcriptPageBusy,setTranscriptPageBusy]=useState(false);
  const [outputPageBusy,setOutputPageBusy]=useState(false);
  const attachNeedRef=useRef<(needId:string,versionId:string)=>void>(()=>{});
  const [actionRouter]=useState(()=>new ClassActionRouter(source=>{referenceOpener.current=document.activeElement instanceof HTMLElement?document.activeElement:null;setReferenceState({classId:activeClassIdRef.current,source});setReferencePageIndex(source.pageIndex);setReferenceOpen(true);setView('notes');},(needId,versionId)=>attachNeedRef.current(needId,versionId)));
  const lookupLibraryReference=useCallback(async(query:string,cue:{kind:string;value:string}|null=null,openUnique=false)=>{
    if(!classId||(!query.trim()&&!cue))return null;
    const scope=classId;const epoch=++libraryLookupEpoch.current;setLibraryBusy(true);setLibraryStatus('Looking through your course references…');
    try{
      const result=await classApi.lookupReference(scope,query,cue);
      if(activeClassIdRef.current!==scope||libraryLookupEpoch.current!==epoch)return null;
      setLibraryCandidates(result.candidates);
      setLibraryStatus(result.ambiguous?'Several references match. Choose the one you want.':result.candidates.length?`${result.candidates.length} reference${result.candidates.length===1?'':'s'} found.`:'No matching course reference is indexed yet.');
      if(openUnique&&!result.ambiguous&&result.candidates.length===1){const source=result.candidates[0];actionRouter.dispatch({type:'open-reference',source});return {title:source.title,pageIndex:source.pageIndex};}
      if(openUnique&&result.candidates.length)setView('materials');
      return null;
    }catch(cause){if(activeClassIdRef.current===scope&&libraryLookupEpoch.current===epoch)setLibraryStatus(cause instanceof Error?cause.message:'Course reference lookup failed.');return null;}
    finally{if(activeClassIdRef.current===scope&&libraryLookupEpoch.current===epoch)setLibraryBusy(false);}
  },[classId,actionRouter]);
  useEffect(()=>{libraryLookupEpoch.current++;setLibraryCandidates([]);setLibraryStatus('');setLibraryBusy(false);},[classId,identityRevision]);
  attachNeedRef.current=(needId,versionId)=>{void attachMaterial(needId,versionId);};
  const cursor=useRef(0),lastEventId=useRef<string|undefined>(undefined),initialized=useRef(false),requestEpoch=useRef(0);
  const snapshotRef=useRef<ClassSnapshot|null>(snapshot);snapshotRef.current=snapshot;
  const policy=normalizeClassPolicy(snapshot?.session.policy,snapshot?.recording.preferences?.keepAudio);
  const followProfessorState=useRef<{classId:string|null;mode:ClassPolicy['followProfessor']|null;seen:Set<string>}>({classId:null,mode:null,seen:new Set()});
  const transcriptDetailsRef=useRef<HTMLDetailsElement|null>(null),transcriptEndRef=useRef<HTMLDivElement|null>(null);
  const transcriptScrollKey=snapshot?`${snapshot.transcriptGeneration??0}:${snapshot.transcript.length}:${snapshot.transcript[snapshot.transcript.length-1]?.id??''}:${snapshot.transcript[snapshot.transcript.length-1]?.endMs??0}`:'';
  const transcriptById=useMemo(()=>new Map([...(snapshot?.transcript||[]),...Object.values(citationSegments)].map(segment=>[segment.id,segment] as const)),[snapshot?.transcript,citationSegments]);
  const openNeedIds=snapshot?.session.needInfo?.filter(need=>need.status==='open').map(need=>need.id).join('|')||'';
  const courseId=snapshot?.session.courseId??null;
  const resourceScope=classId?`${classId}|${courseId??''}|${identityRevision}`:'';
  const currentResourcePreference=resourcePreferenceState?.scope===resourceScope?resourcePreferenceState.snapshot:null;
  const currentResourcePreferences=currentResourcePreference?.preferences??null;
  const currentResourceDraft=resourcePreferenceScope===resourceScope?resourcePreferenceDraft:null;
  const resourcePreferencesReady=Boolean(currentResourcePreference&&currentResourceDraft);
  const resourcePreferencesDirty=Boolean(currentResourcePreferences&&currentResourceDraft&&JSON.stringify(currentResourcePreferences)!==JSON.stringify(currentResourceDraft));
  const maxUploadMibValid=Number.isFinite(Number(maxUploadMibText))&&Number(maxUploadMibText)>0&&Number(maxUploadMibText)<=MAX_CLASS_UPLOAD_MIB;
  const enabledResource=(id:ResourceConnectorId)=>Boolean(currentResourcePreferences?.enabledConnectors.includes(id));
  useEffect(()=>{
    let live=true;const scope=classId?`${classId}|${courseId??''}|${identityRevision}`:'';
    setResourceConnectors([]);setResourceConnectorsScope('');setResourcePreferenceState(null);setResourcePreferenceDraft(null);setResourcePreferenceScope('');setResourcePreferenceError('');
    if(!classId){setResourcePreferenceLoading(false);return;}
    setResourcePreferenceLoading(true);
    void Promise.allSettled([classApi.resourceConnectors(classId),classApi.resourcePreferences(classId)]).then(([connectorsResult,preferencesResult])=>{
      if(!live)return;
      const failures:string[]=[];
      if(connectorsResult.status==='fulfilled'){setResourceConnectors(connectorsResult.value.items);setResourceConnectorsScope(scope);}else failures.push('Could not load available resource sources.');
      if(preferencesResult.status==='fulfilled'){
        const next=preferencesResult.value;setResourcePreferenceState({scope,snapshot:next});setResourcePreferenceDraft(next.preferences);setResourcePreferenceScope(scope);setMaxUploadMibText(formatMebibytes(next.preferences.maxUploadBytes));
      }else failures.push(preferencesResult.reason instanceof Error?preferencesResult.reason.message:'Could not load course resource preferences.');
      setResourcePreferenceError(failures.join(' '));
    }).finally(()=>{if(live)setResourcePreferenceLoading(false);});
    return()=>{live=false;};
  },[classId,courseId,identityRevision,resourcePreferenceReload]);
  useEffect(()=>{referenceRequestEpoch.current++;materialAccessRevision.current=null;setAvailableMaterials([]);setMaterialIntakes([]);setIntakeErrors({});setNeedUrls({});setDriveConnections([]);setDriveConnectionsLoaded(false);setDriveConnectionId('');setDriveFiles([]);setDriveNextPage('');setDriveError('');setCanvasSources([]);setCanvasSourcesLoaded(false);setCanvasSourcesClassId('');setCanvasError('');setCitationSegments({});setCitationBusy({});setTranscriptPageBusy(false);setOutputPageBusy(false);setCueStatus('');setPendingCueNavigation(null);cueNavigationPending.current=false;driveLoadEpoch.current++;canvasLoadEpoch.current++;setReferenceState(null);setReferencePdfSource(null);setReferencePdfState('idle');setReferenceManifest(null);setReferencePageIndex(null);setReferenceOpen(false);},[classId]);
  useEffect(()=>{const reset=()=>{referenceRequestEpoch.current++;materialAccessRevision.current=null;setIdentityRevision(value=>value+1);setSnapshot(null);setLiveCaptions(null);setAvailableMaterials([]);setMaterialIntakes([]);setIntakeErrors({});setNeedUrls({});setReferenceState(null);setReferencePdfSource(null);setReferencePdfState('idle');setReferenceManifest(null);setReferencePageIndex(null);setReferenceOpen(false);setDriveConnections([]);setDriveConnectionsLoaded(false);setDriveConnectionId('');setDriveFiles([]);setDriveNextPage('');setDriveError('');setCanvasSources([]);setCanvasSourcesLoaded(false);setCanvasSourcesClassId('');setCanvasError('');setMaterialBusy('');setError('');driveLoadEpoch.current++;canvasLoadEpoch.current++;};window.addEventListener(ACCOUNT_CHANGED,reset);return()=>window.removeEventListener(ACCOUNT_CHANGED,reset);},[]);
  useEffect(()=>{
    if(!classId)return;let live=true;let pending=false;let controller:AbortController|undefined;let retryDelay=1000;const epoch=++requestEpoch.current;cursor.current=0;lastEventId.current=undefined;initialized.current=false;
    const apply=(next:ClassSnapshot,eventId?:string)=>{
      if(!live||requestEpoch.current!==epoch)return;
      const previousCursor=cursor.current;
      if(next.delta&&previousCursor>next.cursor)return;
      initialized.current=true;cursor.current=next.delta?Math.max(previousCursor,next.cursor):next.cursor;
      const lastEvent=next.events[next.events.length-1];if(eventId)lastEventId.current=eventId;else if(lastEvent)lastEventId.current=lastEvent.id;
      const accessRevision=next.session.materialAccessRevision??0;const accessChanged=next.events.some(event=>event.type==='materials.access_changed')||(materialAccessRevision.current!==null&&materialAccessRevision.current!==accessRevision);materialAccessRevision.current=accessRevision;
      if(accessChanged){referenceRequestEpoch.current++;libraryLookupEpoch.current++;setLibraryCandidates([]);setLibraryStatus('');setLibraryBusy(false);setReferenceState(null);setReferencePdfSource(null);setReferencePdfState('idle');setReferenceManifest(null);setReferencePageIndex(null);setReferenceOpen(false);}
      if(next.transcriptReset)setCitationSegments({});
      setSnapshot(current=>current?.session.id===next.session.id&&next.delta&&current.cursor>next.cursor?current:mergeSnapshot(current,next));setError('');
    };
    const load=async()=>{
      if(pending)return;pending=true;
      try{let catchUp=true;while(live&&catchUp){const next=initialized.current?await classApi.events(classId,cursor.current,true,lastEventId.current):await classApi.snapshot(classId,cursor.current,false);if(!live||requestEpoch.current!==epoch)return;apply(next);catchUp=next.hasMore;if(catchUp)await new Promise(resolve=>setTimeout(resolve,40));}}
      catch(cause){if(live)setError(cause instanceof Error?cause.message:'Connection interrupted. Saved output stays available.');}
      finally{pending=false;}
    };
    const connect=async()=>{
      while(live&&requestEpoch.current===epoch){controller=new AbortController();try{await classApi.stream(classId,cursor.current,lastEventId.current,controller.signal,(next,eventId)=>apply(next,eventId));if(!live||requestEpoch.current!==epoch)return;await load();await new Promise(resolve=>setTimeout(resolve,retryDelay));retryDelay=Math.min(15_000,retryDelay*2);}
        catch(cause){if(!live||requestEpoch.current!==epoch||controller.signal.aborted)return;setError(cause instanceof Error?cause.message:'Connection interrupted. Saved output stays available.');await load();await new Promise(resolve=>setTimeout(resolve,retryDelay));retryDelay=Math.min(15_000,retryDelay*2);}}
    };
    void load().then(()=>{if(live)void connect();});
    return()=>{live=false;controller?.abort();};
  },[classId,identityRevision]);
  useEffect(()=>{setClassMetrics(null);setClassMetricsError('');},[classId]);
  useEffect(()=>{
    if(!classId)return;
    const receive=(event:Event)=>{const detail=(event as CustomEvent<LiveTranscriptionDetail>).detail;if(detail&&classId===`class_${detail.recordingId}`)setLiveCaptions(detail);};
    window.addEventListener(LIVE_LECTURE_TRANSCRIPTION_EVENT,receive);
    return()=>window.removeEventListener(LIVE_LECTURE_TRANSCRIPTION_EVENT,receive);
  },[classId]);
  useEffect(()=>{
    if(!classId||!openNeedIds)return;let live=true;setMaterialsLoading(true);
    void classApi.materials(courseId).then(result=>{if(live)setAvailableMaterials(result.materials);}).catch(cause=>{if(live)setError(cause instanceof Error?cause.message:'Could not load available course sources.');}).finally(()=>{if(live)setMaterialsLoading(false);});
    return()=>{live=false;};
  },[classId,courseId,openNeedIds]);
  const pollingIntakes=materialIntakes.some(intake=>ACTIVE_INTAKE_STATUSES.has(intake.status));
  useEffect(()=>{
    if(!classId)return;let live=true;
    const load=()=>classApi.materialIntakes(classId).then(result=>{if(live)setMaterialIntakes(current=>mergeIntakes(current,result.intakes));}).catch(cause=>{if(live&&openNeedIds)setError(cause instanceof Error?cause.message:'Could not check source imports.');});
    void load();const timer=pollingIntakes?window.setInterval(()=>void load(),2500):undefined;
    return()=>{live=false;if(timer)window.clearInterval(timer);};
  },[classId,openNeedIds,pollingIntakes]);
  useEffect(()=>{for(const intake of materialIntakes)if(TERMINAL_INTAKE_STATUSES.has(intake.status))forgetIntakeCommand(intake.commandId);},[materialIntakes]);
  useEffect(()=>{
    if(!classId)return;
    const receive=(event:Event)=>{
      const detail=(event as CustomEvent<ClassChatOpenRequestDetail>).detail;
      if(!detail||detail.classId!==classId||detail.result)return;
      const current=snapshotRef.current;
      if(!current||current.session.id!==classId||current.session.sessionId!==detail.chatSessionId||current.recording.captureComplete)return;
      const sources=current.outputs.flatMap(output=>output.result?.sources||[]);
      const source=findClassReference(sources,detail.query,detail.pageNumber,detail.cue||null);
      if(!source){detail.pending=lookupLibraryReference(detail.query,detail.libraryCue??(detail.pageNumber!==null?{kind:'physical_page',value:String(detail.pageNumber)}:detail.cue?{kind:detail.cue.kind,value:String(detail.cue.number)}:null),true);return;}
      if(!actionRouter.dispatch({type:'open-reference',source}))return;
      detail.result={title:source.title,pageIndex:source.pageIndex};
    };
    window.addEventListener(CLASS_CHAT_OPEN_REQUEST_EVENT,receive);
    return()=>window.removeEventListener(CLASS_CHAT_OPEN_REQUEST_EVENT,receive);
  },[classId,actionRouter,lookupLibraryReference]);
  useEffect(()=>{
    if(!snapshot||snapshot.session.id!==classId)return;
    const state=followProfessorState.current;
    const seedSeen=()=>{state.classId=snapshot.session.id;state.mode=policy.followProfessor;state.seen=new Set(snapshot.events.map(event=>event.id));};
    if(state.classId!==snapshot.session.id||state.mode!==policy.followProfessor){seedSeen();return;}
    if(policy.followProfessor==='off'||snapshot.recording.captureComplete){for(const event of snapshot.events)state.seen.add(event.id);return;}
    const sources=snapshot.outputs.flatMap(output=>output.result?.sources||[]);
    const transcriptById=new Map(snapshot.transcript.map(segment=>[segment.id,segment] as const));
    for(const event of snapshot.events){
      if(state.seen.has(event.id))continue;
      if(event.type!=='transcript.committed'){state.seen.add(event.id);continue;}
      const data=event.data as {newSegmentIds?:unknown;transcriptReset?:boolean}|null;
      if(!data||data.transcriptReset||!Array.isArray(data.newSegmentIds)){state.seen.add(event.id);continue;}
      const candidates=(data.newSegmentIds as string[]).filter((id):id is string=>typeof id==='string').map(id=>transcriptById.get(id)).filter((segment):segment is ClassSnapshot['transcript'][number]=>segment!==undefined&&segment.speaker==='professor').sort((a,b)=>b.startMs-a.startMs);
      let matched:ClassReference|null=null;
      for(const segment of candidates){
        const intent=parseProfessorReferenceCue(segment.normalizedText||segment.rawText,policy.followProfessor==='all');
        if(!intent)continue;
        matched=findClassReference(sources,intent.query,intent.pageNumber,intent.cue||null);
        if(matched)break;
        state.seen.add(event.id);
        void lookupLibraryReference(intent.query,intent.libraryCue??(intent.pageNumber!==null?{kind:'physical_page',value:String(intent.pageNumber)}:intent.cue?{kind:intent.cue.kind,value:String(intent.cue.number)}:null),true);
        break;
      }
      if(matched){actionRouter.dispatch({type:'open-reference',source:matched});setFollowStatus(`Following the professor to ${matched.title}, page ${matched.pageIndex+1}.`);state.seen.add(event.id);}
    }
  },[snapshot,classId,policy.followProfessor,actionRouter,lookupLibraryReference]);
  useEffect(()=>{
    if(policy.autoScrollLock||cueNavigationPending.current||!transcriptDetailsRef.current?.open)return;
    transcriptEndRef.current?.scrollIntoView({block:'nearest'});
  },[transcriptScrollKey,policy.autoScrollLock]);
  useEffect(()=>{
    if(view!=='notes'||!pendingCueNavigation)return;
    const frame=window.requestAnimationFrame(()=>{
      transcriptDetailsRef.current?.setAttribute('open','');
      const target=document.getElementById(`class-transcript-${pendingCueNavigation}`);
      if(target){target.scrollIntoView({block:'center'});target.focus({preventScroll:true});}
      setPendingCueNavigation(null);
      window.setTimeout(()=>{cueNavigationPending.current=false;},0);
    });
    return()=>window.cancelAnimationFrame(frame);
  },[view,pendingCueNavigation]);
  useEffect(()=>{
    if(!classId||!reference?.versionId){setReferencePdfSource(null);setReferencePdfState('idle');return;}
    let live=true;const epoch=referenceRequestEpoch.current;
    setReferencePdfSource(null);setReferencePdfState('loading');
    void classApi.referencePdfSource(classId,reference.versionId).then(source=>{
      if(live&&referenceRequestEpoch.current===epoch){setReferencePdfSource({classId,versionId:reference.versionId!,...source});setReferencePdfState('ready');}
    }).catch(()=>{if(live&&referenceRequestEpoch.current===epoch)setReferencePdfState('unavailable');});
    return()=>{live=false;};
  },[classId,reference?.versionId]);
  useEffect(()=>{
    if(!classId||!reference?.versionId){setReferenceManifest(null);return;}
    let live=true;const epoch=referenceRequestEpoch.current;setReferenceManifest(null);
    void classApi.referencePdfManifest(classId,reference.versionId).then(manifest=>{if(live&&referenceRequestEpoch.current===epoch)setReferenceManifest(manifest);}).catch(()=>{if(live&&referenceRequestEpoch.current===epoch)setReferenceManifest(null);});
    return()=>{live=false;};
  },[classId,reference?.versionId]);
  if(!classId)return <div className={styles.empty}>Start a class session from your course or the conversation mode menu.</div>;
  if(!snapshot||snapshot.session.id!==classId)return <div className={styles.empty} role="status">{error||'Connecting to your class… Audio saved on this device continues uploading when connected.'}</div>;
  const outputs=snapshot.outputs;
  const transcriptState=transcriptionStatus(snapshot);
  const markers=snapshot.recording.markersMs.filter(marker=>Number.isFinite(marker)&&marker>=0);
  const cueSegments=snapshot.transcript.slice(-5);
  const referenceCues=[...new Map(outputs.flatMap(output=>output.result?.sources||[]).map(source=>[source.spanId,source] as const)).values()].slice(-4);
  const canChangeAudioRetention=['recording','processing'].includes(snapshot.recording.recordingStatus);
  const activeReferenceManifest=reference&&referenceManifest?.versionId===reference.versionId?referenceManifest:null;
  const shownReferencePage=referencePageIndex??reference?.pageIndex??0;
  const shownReferenceLabel=activeReferenceManifest?.pageLabels[shownReferencePage]||String(shownReferencePage+1);
  async function openReferencePdf(){
    if(!reference?.versionId||!classId)return;
    const epoch=referenceRequestEpoch.current;const requestedClassId=classId;const versionId=reference.versionId;
    const tab=window.open('about:blank','_blank');
    if(!tab)return;
    tab.opener=null;
    try{
      const blob=await classApi.referencePdf(requestedClassId,versionId);
      if(referenceRequestEpoch.current!==epoch||activeClassIdRef.current!==requestedClassId){tab.close();return;}
      const objectUrl=URL.createObjectURL(blob);
      if(tab)tab.location.replace(objectUrl);
      window.setTimeout(()=>URL.revokeObjectURL(objectUrl),60_000);
    }catch{tab?.close();if(referenceRequestEpoch.current===epoch)setReferencePdfState('unavailable');}
  }
  async function command(action:string,outputId?:string,nextPolicy?:ClassPolicy){const isPolicyUpdate=action==='update_policy';if(isPolicyUpdate)setPolicyUpdating(true);try{const next=await classApi.command(classId!,snapshot!.session.revision,action,outputId,nextPolicy);cursor.current=next.cursor;const lastEvent=next.events[next.events.length-1];if(lastEvent)lastEventId.current=lastEvent.id;initialized.current=true;if(next.transcriptReset)setCitationSegments({});setSnapshot(next);setError('');}catch(cause){setError(cause instanceof Error?cause.message:'Could not update processing.');}finally{if(isPolicyUpdate)setPolicyUpdating(false);}}
  function setResourceConnectorEnabled(connectorId:ResourceConnectorId,enabled:boolean){setResourcePreferenceDraft(current=>{if(!current)return current;const enabledConnectors=enabled?[...new Set([...current.enabledConnectors,connectorId])]:current.enabledConnectors.filter(id=>id!==connectorId);const connectorOrder=current.connectorOrder.includes(connectorId)?current.connectorOrder:[...current.connectorOrder,connectorId];return {...current,connectorOrder,enabledConnectors};});}
  async function saveResourcePreferences(){
    const current=resourcePreferenceState?.scope===resourceScope?resourcePreferenceState.snapshot:null;const draft=resourcePreferenceScope===resourceScope?resourcePreferenceDraft:null;
    if(!classId||!courseId||!current||!draft)return;
    setResourcePreferenceBusy(true);setResourcePreferenceError('');
    try{const next=await classApi.updateResourcePreferences(classId,current.revision,draft);const scope=`${classId}|${courseId}|${identityRevision}`;setResourcePreferenceState({scope,snapshot:next});setResourcePreferenceDraft(next.preferences);setResourcePreferenceScope(scope);setMaxUploadMibText(formatMebibytes(next.preferences.maxUploadBytes));}
    catch(cause){
      if(cause instanceof LearningApiError&&cause.code==='resource_preferences_revision_conflict'){
        try{const refreshed=await classApi.resourcePreferences(classId);const scope=`${classId}|${courseId}|${identityRevision}`;setResourcePreferenceState({scope,snapshot:refreshed});setResourcePreferenceError('These course preferences changed elsewhere. The latest revision is loaded; review your choices and save again.');}
        catch{setResourcePreferenceError('These course preferences changed elsewhere. Refresh the class before saving again.');}
      }else setResourcePreferenceError(cause instanceof Error?cause.message:'Could not save course resource preferences.');
    }finally{setResourcePreferenceBusy(false);}
  }
  function setMaxUploadMib(value:string){
    setMaxUploadMibText(value);const amount=Number(value);if(!Number.isFinite(amount)||amount<=0||amount>MAX_CLASS_UPLOAD_MIB)return;
    setResourcePreferenceDraft(current=>current?{...current,maxUploadBytes:Math.max(1,Math.round(amount*MEBIBYTE))}:current);
  }
  async function attachMaterial(needId:string,versionId:string){setMaterialBusy(needId+':'+versionId);try{const next=await classApi.attachMaterial(classId!,snapshot!.session.revision,needId,versionId);cursor.current=next.cursor;const lastEvent=next.events[next.events.length-1];if(lastEvent)lastEventId.current=lastEvent.id;initialized.current=true;if(next.transcriptReset)setCitationSegments({});setSnapshot(next);setError('');}catch(cause){setError(cause instanceof Error?cause.message:'Could not attach this course source.');}finally{setMaterialBusy('');}}
  async function submitMaterialIntake(needId:string,body:ClassMaterialIntakeSource,sourceKey:string,file?:File){
    setIntakeBusy(needId);setIntakeErrors(current=>({...current,[needId]:''}));
    try{
      const saved=await stableIntakeCommandId(classId!,needId,sourceKey);
      const previous=materialIntakes.find(intake=>intake.commandId===saved.commandId);
      let commandId=saved.commandId;
      if(previous&&TERMINAL_INTAKE_STATUSES.has(previous.status)){localStorage.removeItem(saved.key);commandId=crypto.randomUUID().replaceAll('-','');localStorage.setItem(saved.key,commandId);}
      const known=await classApi.materialIntakes(classId!,needId);setMaterialIntakes(current=>mergeIntakes(current,known.intakes));
      const pending=known.intakes.find(intake=>ACTIVE_INTAKE_STATUSES.has(intake.status)||intake.status==='awaiting_upload');
      if(pending&&pending.commandId!==commandId){forgetIntakeCommand(commandId);throw new Error(pending.status==='awaiting_upload'?'A file upload is waiting. Select the same file to resume it.':'A source is already being imported for this request.');}
      const intake=await classApi.startMaterialIntake(classId!,needId,{...body,expectedRevision:snapshot!.session.revision,commandId} as ClassMaterialIntakeCreate);
      setMaterialIntakes(current=>mergeIntakes(current,[intake]));
      if(file&&intake.status==='awaiting_upload'){
        if(file.size>50*1024*1024&&intake.resumableUploadPath){
          const session=await classApi.startMaterialUpload(intake.resumableUploadPath);
          const uploaded=await uploadMaterialParts(file,session,{putPart:classApi.uploadMaterialPart,complete:classApi.completeMaterialUpload,onProgress:percentage=>setUploadProgress(current=>({...current,[needId]:percentage}))});
          setMaterialIntakes(current=>mergeIntakes(current,[uploaded]));setUploadProgress(current=>{const next={...current};delete next[needId];return next;});
        }else if(intake.uploadPath){
          const uploaded=await classApi.uploadMaterialIntake(intake.uploadPath,file,body.sourceKind==='upload'?body.mediaType:'application/octet-stream');setMaterialIntakes(current=>mergeIntakes(current,[uploaded]));
        }
      }
      if(intake.status==='failed')forgetIntakeCommand(intake.commandId);
      setNeedUrls(current=>({...current,[needId]:body.sourceKind==='url'?'':current[needId]||''}));
    }catch(cause){setIntakeErrors(current=>({...current,[needId]:cause instanceof Error?cause.message:'The source could not be imported.'}));}
    finally{setIntakeBusy('');}
  }
  async function importNeedUrl(needId:string){const url=needUrls[needId]?.trim();if(!url)return;if(!resourcePreferencesReady||!enabledResource('url')||!currentResourcePreferences?.allowPublicUrls){setIntakeErrors(current=>({...current,[needId]:'Public URL imports are not enabled in this course resource preferences.'}));return;}await submitMaterialIntake(needId,{sourceKind:'url',url},`url:${url}`);}
  async function importNeedFile(needId:string,file:File){
    if(!resourcePreferencesReady||!enabledResource('upload')||!currentResourcePreferences){setIntakeErrors(current=>({...current,[needId]:'File uploads are not enabled in this course resource preferences.'}));return;}
    const lower=file.name.toLowerCase();const mediaType=lower.endsWith('.pdf')?'application/pdf':lower.endsWith('.md')?'text/markdown':lower.endsWith('.txt')?'text/plain':null;
    if(!mediaType){setIntakeErrors(current=>({...current,[needId]:'Choose a PDF, TXT, or Markdown file.'}));return;}
    if(!currentResourcePreferences.acceptedMediaTypes.includes(mediaType as ResourceMediaType)){setIntakeErrors(current=>({...current,[needId]:'This file type is disabled in the course resource preferences.'}));return;}
    if(file.size>currentResourcePreferences.maxUploadBytes){setIntakeErrors(current=>({...current,[needId]:`Choose a file up to ${(currentResourcePreferences.maxUploadBytes/MEBIBYTE).toFixed(1)} MiB.`}));return;}
    try{const contentHash=await fingerprintFile(file);await submitMaterialIntake(needId,{sourceKind:'upload',title:file.name,mediaType,byteCount:file.size},`upload:${file.name}:${mediaType}:${file.size}:${file.lastModified}:${contentHash}`,file);}catch(cause){setIntakeErrors(current=>({...current,[needId]:cause instanceof Error?cause.message:'The file could not be prepared for upload.'}));}
  }
  function driveFileDisabledReason(file:ClassDriveFile){
    if(!resourcePreferencesReady||!currentResourcePreferences)return 'Course resource preferences are still loading.';
    if(!currentResourcePreferences.acceptedMediaTypes.includes(file.mimeType as ResourceMediaType))return 'This file type is not enabled for course imports.';
    const size=Number(file.size||0);const limit=Math.min(DRIVE_MAX_BYTES,currentResourcePreferences.maxUploadBytes);
    if(size>limit)return `This file exceeds the ${(limit/MEBIBYTE).toFixed(1)} MiB Drive import limit.`;
    return '';
  }
  async function loadDriveFiles(needId:string,connectionId:string,pageToken?:string){
    const epoch=++driveLoadEpoch.current;setDriveBusy(needId);setDriveError('');if(!pageToken){setDriveFiles([]);setDriveNextPage('');}
    try{const result=await classApi.driveSources(connectionId,pageToken);if(epoch!==driveLoadEpoch.current||classId!==activeClassIdRef.current)return;const files=result.data?.files||[];setDriveFiles(current=>pageToken?[...current,...files]:files);setDriveNextPage(result.data?.nextPageToken||'');}
    catch(cause){if(epoch===driveLoadEpoch.current)setDriveError(cause instanceof Error?cause.message:'Could not read files from Google Drive. Reconnect and try again.');}
    finally{if(epoch===driveLoadEpoch.current)setDriveBusy('');}
  }
  async function openDrivePicker(needId:string){
    if(driveConnectionsLoaded){if(driveConnectionId&&!driveFiles.length)await loadDriveFiles(needId,driveConnectionId);return;}
    const epoch=++driveLoadEpoch.current;setDriveBusy(needId);setDriveError('');
    try{const result=await classApi.driveConnections();if(epoch!==driveLoadEpoch.current||classId!==activeClassIdRef.current)return;const available=result.items.filter(connection=>connection.status==='connected'&&connection.capabilities?.includes('drive_read'));setDriveConnections(available);setDriveConnectionsLoaded(true);const selected=available.find(connection=>connection.id===driveConnectionId)||available[0];if(selected){setDriveConnectionId(selected.id);void loadDriveFiles(needId,selected.id);}else setDriveError(result.enabled?'Connect a Google account with Drive read access, then reopen this picker.':'Google Drive connections are not enabled on this server.');}
    catch(cause){if(epoch===driveLoadEpoch.current){setDriveError(cause instanceof Error?cause.message:'Could not check connected Google Drive accounts.');setDriveConnectionsLoaded(false);}}
    finally{if(epoch===driveLoadEpoch.current)setDriveBusy('');}
  }
  function importNeedDrive(needId:string,file:ClassDriveFile){if(!driveConnectionId)return;if(!resourcePreferencesReady||!enabledResource('drive')){setIntakeErrors(current=>({...current,[needId]:'Google Drive imports are not enabled in this course resource preferences.'}));return;}const reason=driveFileDisabledReason(file);if(reason){setIntakeErrors(current=>({...current,[needId]:reason}));return;}void submitMaterialIntake(needId,{sourceKind:'drive',connectionId:driveConnectionId,fileId:file.id},`drive:${driveConnectionId}:${file.id}`);}
  async function loadCanvasSources(needId:string){
    if(!classId)return;const requestedClassId=classId;const epoch=++canvasLoadEpoch.current;setCanvasBusy(needId);setCanvasError('');
    try{const result=await classApi.canvasSources(requestedClassId);if(epoch!==canvasLoadEpoch.current||requestedClassId!==activeClassIdRef.current)return;setCanvasSources(result.items);setCanvasSourcesLoaded(true);setCanvasSourcesClassId(requestedClassId);}
    catch(cause){if(epoch===canvasLoadEpoch.current)setCanvasError(cause instanceof Error?cause.message:'Could not load previously synced Canvas course text.');}
    finally{if(epoch===canvasLoadEpoch.current)setCanvasBusy('');}
  }
  function openCanvasPicker(needId:string){if(!canvasSourcesLoaded||canvasSourcesClassId!==classId)void loadCanvasSources(needId);}
  function importNeedCanvas(needId:string,source:ClassCanvasSource){if(!resourcePreferencesReady||!enabledResource('canvas')){setIntakeErrors(current=>({...current,[needId]:'Canvas imports are not enabled in this course resource preferences.'}));return;}void submitMaterialIntake(needId,{sourceKind:'canvas',connectionId:source.connectionId,entityId:source.entityId},`canvas:${source.connectionId}:${source.entityId}:${source.sourceRevision}`);}
  async function loadMoreTranscript(){
    const current=snapshotRef.current;const requestedClassId=classId;
    if(!requestedClassId||!current?.transcriptHasMore||!current.transcriptCursor||transcriptPageBusy)return;
    setTranscriptPageBusy(true);
    try{
      const page=await classApi.transcriptPage(requestedClassId,current.transcriptCursor);
      if(activeClassIdRef.current!==requestedClassId)return;
      setSnapshot(latest=>{
        if(!latest||latest.session.id!==current.session.id||(latest.transcriptGeneration??0)!==page.generation)return latest;
        const segments=new Map(latest.transcript.map(segment=>[segment.id,segment] as const));
        for(const segment of page.items)segments.set(segment.id,segment);
        return {...latest,transcript:[...segments.values()].sort((a,b)=>a.startMs-b.startMs||a.id.localeCompare(b.id)),transcriptHasMore:page.hasMore,transcriptCursor:page.nextCursor};
      });
    }catch(cause){if(activeClassIdRef.current===requestedClassId)setError(cause instanceof Error?cause.message:'Could not load more transcript passages.');}
    finally{setTranscriptPageBusy(false);}
  }
  async function loadMoreOutputs(){
    const current=snapshotRef.current;const requestedClassId=classId;
    if(!requestedClassId||!current?.outputHasMore||!current.outputCursor||outputPageBusy)return;
    setOutputPageBusy(true);
    try{
      const page=await classApi.outputsPage(requestedClassId,current.outputCursor);
      if(activeClassIdRef.current!==requestedClassId)return;
      setSnapshot(latest=>{
        if(!latest||latest.session.id!==current.session.id||(latest.outputGeneration??0)!==page.generation)return latest;
        const outputs=new Map(latest.outputs.map(output=>[output.id,output] as const));
        for(const item of page.items){const previous=outputs.get(item.id);if(!previous||item.revision>=previous.revision)outputs.set(item.id,item);}
        const merged=[...outputs.values()].sort((a,b)=>(a.windowStartMs??0)-(b.windowStartMs??0)||a.kind.localeCompare(b.kind)||a.id.localeCompare(b.id));
        return {...latest,outputs:merged,outputHasMore:page.hasMore,outputCursor:page.nextCursor};
      });
    }catch(cause){if(activeClassIdRef.current===requestedClassId)setError(cause instanceof Error?cause.message:'Could not load earlier class results.');}
    finally{setOutputPageBusy(false);}
  }
  async function toggleCitations(ids:string[],key:string){
    if(revealed[key]){setRevealed(current=>({...current,[key]:false}));return;}
    const requestedClassId=classId;const current=snapshotRef.current;
    if(!requestedClassId||!current)return;
    const known=new Set([...current.transcript.map(segment=>segment.id),...Object.keys(citationSegments)]);
    const missing=ids.filter(id=>!known.has(id));
    if(missing.length){
      setCitationBusy(state=>({...state,[key]:true}));
      try{
        const page=await classApi.transcriptSegments(requestedClassId,missing);
        if(activeClassIdRef.current!==requestedClassId)return;
        setCitationSegments(state=>({...state,...Object.fromEntries(page.items.map(segment=>[segment.id,segment]))}));
      }catch(cause){if(activeClassIdRef.current===requestedClassId)setError(cause instanceof Error?cause.message:'Could not load cited transcript passages.');}
      finally{setCitationBusy(state=>({...state,[key]:false}));}
    }
    if(activeClassIdRef.current===requestedClassId)setRevealed(state=>({...state,[key]:true}));
  }
  function citations(ids:string[],key:string){return <><button type="button" disabled={Boolean(citationBusy[key])} onClick={()=>void toggleCitations(ids,key)}>{citationBusy[key]?'Loading lecture evidence…':revealed[key]?'Hide lecture evidence':'Show lecture evidence'}</button>{revealed[key]?ids.map(id=>transcriptById.get(id)).filter((segment):segment is ClassSnapshot['transcript'][number]=>segment!==undefined).sort((a,b)=>a.startMs-b.startMs).map(segment=><blockquote key={segment.id}><small>{Math.floor(segment.startMs/1000)}–{Math.floor(segment.endMs/1000)}s</small>{segment.normalizedText||segment.rawText}</blockquote>):null}</>;}
  function jumpToTranscript(segmentId:string,message:string){cueNavigationPending.current=true;setCueStatus(message);setPendingCueNavigation(segmentId);setView('notes');}
  function jumpToMarker(markerMs:number,index:number){
    const nearest=(snapshot?.transcript??[]).reduce<ClassSnapshot['transcript'][number]|null>((best,segment)=>!best||Math.abs(segment.startMs-markerMs)<Math.abs(best.startMs-markerMs)?segment:best,null);
    if(!nearest){setCueStatus(`Marker ${index+1} at ${formatCueTime(markerMs)}. No transcript passage is loaded yet.`);return;}
    jumpToTranscript(nearest.id,`Marker ${index+1} at ${formatCueTime(markerMs)}. Showing the nearest loaded passage at ${formatCueTime(nearest.startMs)}.`);
  }
  function output(item:ClassOutput){
    const needForWindow=item.kind==='materials'?snapshot!.session.needInfo?.find(entry=>entry.windowId===item.windowId):undefined;
    const need=needForWindow?.status==='open'?needForWindow:undefined;
    const needIntake=needForWindow?materialIntakes.find(intake=>intake.needId===needForWindow.id):undefined;
    const intakeInProgress=Boolean(needIntake&&(ACTIVE_INTAKE_STATUSES.has(needIntake.status)||needIntake.status==='awaiting_upload'));
    if(item.status!=='ready')return <div key={item.id} className={styles.output}><strong>{item.kind.replaceAll('_',' ')}</strong><p role="status">{item.error||(item.status==='paused'?'Paused by your current preferences.':item.status==='retrying'?'A temporary issue came up; retrying…':'Preparing quietly…')}</p>{needIntake?<small>{needIntake.status==='attached'?'Source attached; checking for a matching passage.':needIntake.status==='failed'?needIntake.error||'Source import failed.':`Source import · ${needIntake.status.replaceAll('_',' ')}`}</small>:null}{item.status==='failed'?<Button size="sm" variant="outline" onClick={()=>void command('retry',item.id)}>Retry this output</Button>:null}</div>;
    const result=item.result;
    return <section key={item.id} className={styles.output}>
      {item.kind==='flashcards' && result?.deckId?<Button onClick={()=>void actionRouter.dispatch({type:'open-flashcards',deckId:result.deckId!})}>Open draft deck</Button>:null}
      {item.kind==='notes'&&item.reconciles?.length?<small role="status">Updated after a transcript revision.</small>:null}
      {result?.blocks?.map((block,index)=><div key={index}><h3>{block.title}</h3><RichContent body={block.body}/><small>Lecture evidence: {block.segmentIds.length} passages · {item.kind==='notes'?(item.settlement==='settled'?'Settled note':item.settlement==='partial'?'Partial coverage':item.provisional===false?'Finalized note':'Live draft'):'Generated summary'}</small>{citations(block.segmentIds,item.id+':evidence:'+index)}</div>)}
      {result?.sources?.map(source=><button className={styles.source} type="button" key={source.spanId} onClick={()=>void actionRouter.dispatch({type:'open-reference',source})}><strong>{source.title} · Page {source.pageLabel||source.pageIndex+1}{source.pageLabel&&source.pageLabel!==String(source.pageIndex+1)?` (PDF page ${source.pageIndex+1})`:''}</strong><p>{source.text.slice(0,500)}</p><small>Supporting material · supplementary to the lecture</small></button>)}
      {item.kind==='materials'&&!result?.sources?.length?<div className={styles.needInfo}>
        <strong>No matching passage yet</strong><p>{need?.prompt||'No useful passage was found in the current materials.'}</p>
        {materialsLoading?<p role="status">Checking your available course materials…</p>:null}
        {need&&policy.materials&&!snapshot!.session.cancelled?availableMaterials.filter(material=>['ready','partially_ready'].includes(material.status)&&!['answer_key','sample_paper'].includes(material.role)).slice(0,8).map(material=><Button key={material.versionId} size="sm" variant="outline" disabled={!resourcePreferencesReady||!enabledResource('library')||Boolean(materialBusy)||intakeBusy===need.id||intakeInProgress} onClick={()=>actionRouter.dispatch({type:'resolve-need',needId:need.id,versionId:material.versionId})}>{materialBusy===need.id+':'+material.versionId?'Attaching…':'Use '+material.title}</Button>):null}
        {need&&policy.materials&&!snapshot!.session.cancelled&&resourcePreferencesReady&&!enabledResource('library')?<small>Course library selection is disabled in the course resource preferences.</small>:null}
        {need&&policy.materials&&!snapshot!.session.cancelled?<>
          <form className={styles.intakeForm} onSubmit={event=>{event.preventDefault();void importNeedUrl(need.id);}}>
            <label>Import a public URL<input type="url" maxLength={2048} disabled={!resourcePreferencesReady||!enabledResource('url')||!currentResourcePreferences?.allowPublicUrls} value={needUrls[need.id]||''} onChange={event=>setNeedUrls(current=>({...current,[need.id]:event.target.value}))} placeholder="https://example.edu/lecture-notes" /></label>
            <Button size="sm" type="submit" disabled={!resourcePreferencesReady||!enabledResource('url')||!currentResourcePreferences?.allowPublicUrls||intakeBusy===need.id||intakeInProgress||!needUrls[need.id]?.trim()}>{intakeBusy===need.id?'Starting import…':'Import URL'}</Button>
          </form>
          {!resourcePreferencesReady?<small role="status">Loading course source preferences…</small>:!enabledResource('url')?<small>Public URL sources are disabled in this course.</small>:!currentResourcePreferences?.allowPublicUrls?<small>Public URL imports are turned off for this course.</small>:null}
          <label className={styles.intakeFile}>Upload a PDF, TXT, or Markdown file<input type="file" accept=".pdf,.txt,.md,application/pdf,text/plain,text/markdown" disabled={!resourcePreferencesReady||!enabledResource('upload')||intakeBusy===need.id||(intakeInProgress&&needIntake?.status!=='awaiting_upload')} onChange={event=>{const file=event.currentTarget.files?.[0];event.currentTarget.value='';if(file)void importNeedFile(need.id,file);}} /></label>
          {!resourcePreferencesReady?<small role="status">Loading course source preferences…</small>:!enabledResource('upload')?<small>File uploads are disabled in this course.</small>:<small>Maximum file size: {(currentResourcePreferences!.maxUploadBytes/MEBIBYTE).toFixed(1)} MiB. Accepted formats: PDF, TXT, and Markdown.</small>}
        </>:null}
        {needIntake?<p className={styles.intakeStatus} role="status">{uploadProgress[needIntake.needId]!==undefined?'Uploading source · '+uploadProgress[needIntake.needId]+'%':needIntake.status==='awaiting_upload'?'Choose the same file to resume its upload.':needIntake.status==='queued'||needIntake.status==='fetching'||needIntake.status==='uploading'||needIntake.status==='processing'?'Importing source · '+needIntake.status.replaceAll('_',' '):needIntake.status==='attached'?'Source attached; checking for a matching passage.':needIntake.error||'Source import failed.'}</p>:null}
        {intakeErrors[need?.id||'']?<p className={styles.intakeError} role="alert">{intakeErrors[need?.id||'']}</p>:null}
        {need&&!policy.materials?<small>Enable related course materials before adding a source.</small>:null}
        <small>Imported sources are treated as supporting evidence. They do not replace lecture notes or run instructions found in the source.</small>
      </div>:null}
      {need&&item.kind==='materials'&&!result?.sources?.length&&policy.materials&&!snapshot!.session.cancelled&&enabledResource('drive')?<details className={styles.drivePicker} onToggle={event=>{if(event.currentTarget.open)void openDrivePicker(need.id);}}>
        <summary>Choose from Google Drive</summary>
        {driveConnections.length?<>
          <label>Connected account<select value={driveConnectionId} onChange={event=>{setDriveConnectionId(event.target.value);if(event.target.value)void loadDriveFiles(need.id,event.target.value);}}><option value="">Select account</option>{driveConnections.map(connection=><option key={connection.id} value={connection.id}>{connection.email||'Google account'}</option>)}</select></label>
          <div className={styles.driveFiles}>{driveFiles.map(file=>{const reason=driveFileDisabledReason(file);return <button type="button" key={file.id} disabled={Boolean(reason)||intakeBusy===need.id||intakeInProgress||Boolean(driveBusy)} onClick={()=>importNeedDrive(need.id,file)}><strong>{file.name}</strong><small>{file.mimeType.replace('application/','').replace('text/','').toUpperCase()}{file.size?' · '+(Number(file.size)/1_000_000).toFixed(1)+' MB':''}</small>{reason?<small>{reason}</small>:null}</button>;})}</div>
          {driveBusy===need.id?<small role="status">Loading Drive files…</small>:null}
          {driveNextPage?<Button size="sm" variant="outline" type="button" disabled={Boolean(driveBusy)} onClick={()=>void loadDriveFiles(need.id,driveConnectionId,driveNextPage)}>Load more files</Button>:null}
          {!driveFiles.length&&!driveBusy?<small>No files were found in this Drive page.</small>:null}
        </>:driveConnectionsLoaded&&!driveConnections.length?<small>Connect Google Drive with read access to use a file here.</small>:driveBusy===need.id?<small role="status">Checking connected accounts…</small>:null}
        {driveError?<small className={styles.intakeError} role="alert">{driveError}</small>:null}
        <small>Open Learn reads the selected file only after you choose it. Files are added as untrusted supporting material.</small>
      </details>:need&&item.kind==='materials'&&!result?.sources?.length&&policy.materials&&!snapshot!.session.cancelled&&resourcePreferencesReady?<small>Google Drive imports are disabled in this course.</small>:null}
      {need&&item.kind==='materials'&&!result?.sources?.length&&policy.materials&&!snapshot!.session.cancelled&&enabledResource('canvas')?<details className={styles.canvasPicker} onToggle={event=>{if(event.currentTarget.open)openCanvasPicker(need.id);}}>
        <summary>Use previously synced Canvas text</summary>
        <small>Choose course coverage text already synced from Canvas. Open Learn does not fetch Canvas files or assignments here.</small>
        {canvasSourcesClassId===classId&&canvasSources.length?<div className={styles.canvasSources}>{canvasSources.map(source=><article key={source.connectionId+':'+source.entityId}>
          <strong>{source.title}</strong><p>{source.preview}</p>
          <Button size="sm" variant="outline" type="button" disabled={!resourcePreferencesReady||intakeBusy===need.id||intakeInProgress||Boolean(canvasBusy)} onClick={()=>importNeedCanvas(need.id,source)}>Add this Canvas text</Button>
        </article>)}</div>:null}
        {canvasBusy===need.id?<small role="status">Loading previously synced course text…</small>:null}
        {canvasSourcesLoaded&&canvasSourcesClassId===classId&&!canvasSources.length&&!canvasBusy?<small>No previously synced Canvas coverage text is available for this course.</small>:null}
        {canvasError?<small className={styles.intakeError} role="alert">{canvasError}</small>:null}
        <Button size="sm" variant="outline" type="button" disabled={!resourcePreferencesReady||Boolean(canvasBusy)} onClick={()=>void loadCanvasSources(need.id)}>Refresh Canvas sources</Button>
        <small>Selected text is added as untrusted supporting material and keeps its Canvas source provenance.</small>
      </details>:need&&item.kind==='materials'&&!result?.sources?.length&&policy.materials&&!snapshot!.session.cancelled&&resourcePreferencesReady?<small>Canvas imports are disabled in this course.</small>:null}
      {result?.items?.map((card,index)=>{const key=item.id+':'+index;return <div key={key} className={styles.card}><RichContent body={card.prompt}/>{revealed[key]?<RichContent body={card.answer}/>:null}<button type="button" onClick={()=>setRevealed(current=>({...current,[key]:!current[key]}))}>{revealed[key]?'Hide answer':'Reveal answer'}</button><small>{item.kind==='flashcards'?'Draft card · not scheduled for review':'Active recall'} · {card.segmentIds.length} lecture passages</small>{citations(card.segmentIds,key+':evidence')}</div>;})}
      {result?.quizId?<><p>{item.kind==='revision_quiz'?'Revision quiz':'Practice the material covered so far'}</p><Button size="sm" onClick={()=>void actionRouter.dispatch({type:'open-quiz',sessionId:snapshot!.session.sessionId,quizId:result.quizId!})}>Open quiz</Button><small>Questions and feedback use the shared quiz experience.</small></>:null}
      {result?.evidenceMode==='hierarchical'?<p>Long-class synthesis uses bounded layers across {result.sourceWindowCount??'the available'} transcript windows. Details may be compressed; follow the citations to review the original passages.</p>:result?.boundedCoverage?<p>Coverage is limited to a bounded selection of this class.</p>:null}
    </section>;
  }
  return <section className={styles.workspace} aria-label="In-Class workspace">
      <p className={styles.srOnly} role="status" aria-live="polite">{followStatus} {cueStatus}</p>
    <header>{buddies.snapshot?.profiles.filter(buddy=>buddy.id===snapshot.session.buddyId).map(buddy=><div key={buddy.id}><BuddyAvatar buddy={buddy}/><strong>{buddy.name}</strong></div>)}<h2>{snapshot.session.title}</h2><p>{snapshot.session.processing.replaceAll('-',' ')} · {snapshot.recording.captureComplete?'Capture stopped':'Capture remains on its recording device'} · {snapshot.recording.chunks.transcribed} slices transcribed</p><div className={styles.transcriptionStatus} data-state={transcriptState.state} role="status" aria-live="polite" aria-atomic="true" aria-label={`Transcription status: ${transcriptState.label}`}><strong>{transcriptState.label}</strong><span>{transcriptState.detail}</span></div><small>Recording controls stay in the workspace shell. Opening this class never starts a microphone.</small></header>
    <nav aria-label="Class views" className={styles.tabs}>{['notes','materials','practice','package'].map(tab=><button type="button" aria-pressed={view===tab} key={tab} onClick={()=>setView(tab)}>{tab==='package'?'Revision':tab[0].toUpperCase()+tab.slice(1)}{tab==='practice'?` (${outputs.filter(o=>['practice','flashcards'].includes(o.kind)&&o.status==='ready').length})`:''}</button>)}</nav>
    <details className={styles.preferences}>
      <summary>Processing preferences</summary>
      <p>Updates apply while class processing runs. Notes can backfill retained windows; enabling materials, practice or flashcards starts with the newest settled window.</p>
      <fieldset disabled={policyUpdating||snapshot.session.cancelled||snapshot.session.outputTransitionPending}>
        <legend>Prepare during class</legend>
        {([['notes','Live notes'],['materials','Related course materials'],['flashcards','Flashcard drafts']] as const).map(([key,label])=><label key={key}><input type="checkbox" checked={policy[key]} onChange={event=>void command('update_policy',undefined,{...policy,[key]:event.currentTarget.checked})}/>{label}</label>)}
      </fieldset>
      <fieldset disabled={policyUpdating||snapshot.session.cancelled||snapshot.session.outputTransitionPending}>
        <legend>Study behavior</legend>
        <label>Note detail<select value={policy.noteDensity} onChange={event=>void command('update_policy',undefined,{...policy,noteDensity:event.currentTarget.value as ClassPolicy['noteDensity']})}><option value="concise">Concise</option><option value="standard">Standard</option><option value="detailed">Detailed</option></select></label>
        <label>Practice cadence<select value={policy.practiceCadence} onChange={event=>{const practiceCadence=event.currentTarget.value as ClassPolicy['practiceCadence'];void command('update_policy',undefined,{...policy,practiceCadence,practice:practiceCadence!=='off'});}}><option value="off">Off</option><option value="every_10_minutes">Every 10 minutes</option><option value="every_20_minutes">Every 20 minutes</option><option value="at_end">At the end</option></select></label>
        <label>Follow professor<select value={policy.followProfessor} onChange={event=>void command('update_policy',undefined,{...policy,followProfessor:event.currentTarget.value as ClassPolicy['followProfessor']})}><option value="off">Off</option><option value="explicit">Follow page, slide, chapter, or figure cues</option><option value="all">Also follow uniquely matched material references</option></select></label>
        <label><input type="checkbox" checked={policy.showInterimTranscript} onChange={event=>void command('update_policy',undefined,{...policy,showInterimTranscript:event.currentTarget.checked})}/>Show provisional live captions</label>
        <label>Transcript text size<select value={policy.transcriptFontScale} onChange={event=>void command('update_policy',undefined,{...policy,transcriptFontScale:event.currentTarget.value as ClassPolicy['transcriptFontScale']})}><option value="small">Small</option><option value="standard">Standard</option><option value="large">Large</option></select></label>
        <label><input type="checkbox" checked={policy.autoScrollLock} onChange={event=>void command('update_policy',undefined,{...policy,autoScrollLock:event.currentTarget.checked})}/>Lock transcript position while reading</label>
      </fieldset>
      <fieldset disabled={policyUpdating||snapshot.session.cancelled||snapshot.session.outputTransitionPending}>
        <legend>Audio retention</legend>
        <label><input type="checkbox" checked={policy.keepAudio} disabled={!canChangeAudioRetention} onChange={event=>void command('update_policy',undefined,{...policy,keepAudio:event.currentTarget.checked})}/>Keep original class audio for playback</label>
        <small>{canChangeAudioRetention?'Turn this off to remove server audio after transcription finishes; saved notes and transcript remain.':snapshot.recording.stages.audioRetention==='removed'?'The original audio has been removed; notes and transcript remain.':'Audio retention is finalized for this recording.'}</small>
      </fieldset>
      <fieldset disabled={policyUpdating||snapshot.session.cancelled||snapshot.session.outputTransitionPending}>
        <legend>Buddy notifications</legend>
        <label><input type="checkbox" checked={policy.buddyQuietDuringClass} onChange={event=>void command('update_policy',undefined,{...policy,buddyQuietDuringClass:event.currentTarget.checked})}/>Keep Buddy quiet for this class</label>
        <small>Suppresses the inbox message when the revision package is ready. Notes and study outputs still appear here.</small>
      </fieldset>
      {snapshot.session.cancelled?<small>Resume processing before changing preferences.</small>:null}
      {snapshot.session.outputTransitionPending?<small role="status">Updating class processing. These controls will unlock when the saved outputs are reconciled.</small>:null}
    </details>
    {reference?<button className={styles.referenceToggle} type="button" aria-pressed={referenceOpen} onClick={()=>setReferenceOpen(open=>!open)}>{referenceOpen?'Hide reference':'Show reference'} · {reference.title}</button>:null}
    {markers.length||cueSegments.length||referenceCues.length?<nav className={styles.cueRail} aria-label="Live class cues and recording markers"><strong>Live cues</strong><div className={styles.cueList}>{markers.map((marker,index)=><button key={`marker-${index}-${marker}`} type="button" className={styles.markerCue} onClick={()=>jumpToMarker(marker,index)} aria-label={`Recording marker ${index+1} at ${formatCueTime(marker)}; jump to nearest loaded transcript passage`}><span aria-hidden="true">◆</span> Marker {index+1} · {formatCueTime(marker)}</button>)}{cueSegments.map(segment=>{const text=(segment.normalizedText||segment.rawText).replace(/\s+/g,' ').trim();const excerpt=text.length>72?`${text.slice(0,69)}…`:text;return <button key={segment.id} type="button" className={styles.transcriptCue} onClick={()=>jumpToTranscript(segment.id,`Showing transcript passage at ${formatCueTime(segment.startMs)}.`)} aria-label={`Transcript cue at ${formatCueTime(segment.startMs)}: ${text}`}><time>{formatCueTime(segment.startMs)}</time><span>{excerpt||'Transcript passage'}</span></button>;})}{referenceCues.map(source=><button key={source.spanId} type="button" className={styles.markerCue} onClick={()=>void actionRouter.dispatch({type:'open-reference',source})} aria-label={`Open course reference ${source.title}, page ${source.pageLabel||source.pageIndex+1}`}><span aria-hidden="true">↗</span> {source.title} · p. {source.pageLabel||source.pageIndex+1}</button>)}</div>{cueStatus?<small>{cueStatus}</small>:null}</nav>:null}
    <div className={styles.stage} data-reference-open={referenceOpen&&Boolean(reference)}>
      <div className={styles.stageMain}>
        {view==='materials'&&snapshot.session.needInfoHasMore?<Button disabled={needsPageBusy} onClick={()=>{
          const scope=classId;const after=snapshot.session.needInfoNextCursor;if(!scope||!after)return;setNeedsPageBusy(true);
          void classApi.needs(scope,after).then(page=>{if(activeClassIdRef.current!==scope)return;setSnapshot(current=>current?{...current,session:{...current.session,needInfo:[...new Map([...(current.session.needInfo??[]),...page.items].map(need=>[need.id,need])).values()],needInfoHasMore:page.hasMore,needInfoNextCursor:page.nextCursor}}:current);}).catch(cause=>{if(activeClassIdRef.current===scope)setError(String(cause));}).finally(()=>{if(activeClassIdRef.current===scope)setNeedsPageBusy(false);});
        }}>{needsPageBusy?'Loading resource requests…':'Load more resource requests'}</Button>:null}
        {view==='materials'?<section className={styles.output} aria-label="Course reference lookup">
          <h3>Find a course reference</h3>
          <form onSubmit={event=>{event.preventDefault();void lookupLibraryReference(libraryQuery,libraryCueKind&&libraryCueValue.trim()?{kind:libraryCueKind,value:libraryCueValue.trim()}:null);}}>
            <label>Topic or document title<input value={libraryQuery} maxLength={200} onChange={event=>setLibraryQuery(event.currentTarget.value)}/></label>
            <label>Reference cue<select value={libraryCueKind} onChange={event=>setLibraryCueKind(event.currentTarget.value)}><option value="">Topic only</option>{[['physical_page','PDF page'],['page_label','Printed page label'],['chapter','Chapter'],['section','Section'],['slide','Slide'],['figure','Figure'],['equation','Equation']].map(([kind,label])=><option key={kind} value={kind}>{label}</option>)}</select></label>
            {libraryCueKind?<label>Cue number or label<input maxLength={100} value={libraryCueValue} onChange={event=>setLibraryCueValue(event.currentTarget.value)}/></label>:null}
            <Button type="submit" disabled={libraryBusy||(!libraryQuery.trim()&&!(libraryCueKind&&libraryCueValue.trim()))}>{libraryBusy?'Finding references…':'Find references'}</Button>
          </form>
          <p role="status">{libraryStatus}</p>
          {libraryCandidates.map(source=><button key={source.spanId} type="button" className={styles.source} onClick={()=>actionRouter.dispatch({type:'open-reference',source})}>{source.title} · Page {source.pageLabel||source.pageIndex+1}<p>{source.text.slice(0,300)}</p></button>)}
        </section>:null}
        {view==='notes'&&(snapshot.provisionalNotes?.length??0)>0?<section className={styles.output} aria-label="Caption notes">
          <h3>Fast notes · provisional</h3><p>These drafts use live captions. Recorded audio replaces them with archived transcript evidence; your saved note edits remain separate.</p>
          {(snapshot.provisionalNotes??[]).slice(-20).map(note=><article key={note.id}>
            <small>{formatCueTime(note.startMs)} · {note.status==='reconciled'?'Replaced by archived transcript':note.status==='unmatched'?'Unverified — no overlapping archived speech':snapshot.session.cancelled?'Processing paused':note.status==='ready'?'Caption draft':note.status==='failed'?'Draft failed':'Preparing caption draft'}</small>
            {note.status!=='reconciled'?note.result.blocks?.map((block,index)=><div key={index}><h4>{block.title}</h4><RichContent body={block.body}/></div>):null}
            {note.error?<p>{note.error}</p>:null}
            {note.status==='failed'?<Button disabled={snapshot.session.cancelled||!policy.notes} onClick={()=>{const scope=classId;if(!scope)return;void classApi.retryProvisionalNote(scope,note.id,note.revision).then(next=>{if(activeClassIdRef.current===scope)setSnapshot(current=>mergeSnapshot(current,next));}).catch(cause=>setError(String(cause)));}}>Retry caption draft</Button>:null}
            {note.authoritativeSources.length?citations(note.authoritativeSources.map(source=>source.segmentId),note.id):null}
          </article>)}
        </section>:null}
        {error?<p role="alert">{error}</p>:null}
        {view==='materials'?<details className={styles.resourcePreferences}>
          <summary>Course resource sources</summary>
          <p>These defaults apply to every class in this course. Sources are read only after you select them; Blackboard and Moodle are adapter stubs.</p>
          {resourcePreferenceLoading&&!resourcePreferencesReady?<p role="status">Loading course source preferences…</p>:null}
          {resourcePreferenceError?<div><p role="alert">{resourcePreferenceError}</p><Button size="sm" type="button" variant="outline" disabled={resourcePreferenceLoading} onClick={()=>setResourcePreferenceReload(value=>value+1)}>Refresh preferences</Button></div>:null}
          {!courseId?<small>Add this class to a course to save source preferences.</small>:null}
          <fieldset disabled={!currentResourceDraft||resourcePreferenceLoading||resourcePreferenceBusy||!courseId}>
            <legend>Enabled source types</legend>
            {resourceConnectorsScope===resourceScope?resourceConnectors.map(connector=>connector.status==='supported'?<label key={connector.id}><input type="checkbox" checked={currentResourceDraft?.enabledConnectors.includes(connector.id)??false} onChange={event=>setResourceConnectorEnabled(connector.id,event.currentTarget.checked)}/><span>{connector.name}<small>{connector.detail}</small></span></label>:<label key={connector.id}><input type="checkbox" checked={false} disabled aria-label={`${connector.name} is not available yet`}/><span>{connector.name} — Not available yet<small>{connector.detail}</small></span></label>):<small role="status">Loading supported and planned sources…</small>}
          </fieldset>
          <fieldset disabled={!currentResourceDraft||resourcePreferenceLoading||resourcePreferenceBusy||!courseId}>
            <legend>Import limits</legend>
            <label><input type="checkbox" checked={currentResourceDraft?.allowPublicUrls??false} onChange={event=>setResourcePreferenceDraft(current=>current?{...current,allowPublicUrls:event.currentTarget.checked}:current)}/>Allow public URL imports</label>
            <label className={styles.resourceLimit}>Maximum file size (MiB)<input type="number" min="0.000001" max={MAX_CLASS_UPLOAD_MIB} step="any" value={maxUploadMibText} onChange={event=>setMaxUploadMib(event.currentTarget.value)}/></label>
            <small>Supported file types: {currentResourcePreferences?.acceptedMediaTypes.map(type=>type==='application/pdf'?'PDF':type==='text/plain'?'TXT':'Markdown').join(', ')||'PDF, TXT, and Markdown'}.</small>
          </fieldset>
          <Button size="sm" type="button" disabled={!courseId||!resourcePreferencesReady||!resourcePreferencesDirty||!maxUploadMibValid||resourcePreferenceBusy||resourcePreferenceLoading} onClick={()=>void saveResourcePreferences()}>{resourcePreferenceBusy?'Saving course preferences…':'Save course preferences'}</Button>
        </details>:null}
        {view==='materials'?<details className={styles.resourcePreferences}>
          <summary>Find a YouTube video</summary>
          <ClassYoutubeSearch classId={snapshot.session.id}/>
        </details>:null}
        {policy.showInterimTranscript&&((liveCaptions&&liveCaptions.recordingId===snapshot.session.recordingId&&liveCaptions.status!=='stopped')||(snapshot.liveTranscript?.length??0)>0)?<section className={styles.liveCaptions} aria-label="Provisional live transcript"><strong>Live transcript · provisional</strong><small>Committed captions create provisional drafts. Recorded audio remains authoritative and replaces those drafts when transcription catches up. Interim text expires after ten minutes.</small>{liveCaptions?.error?<p role="status">{liveCaptions.error}</p>:null}{liveCaptions?.persistenceError?<p role="alert">{liveCaptions.persistenceError}</p>:null}<div aria-live="polite" aria-relevant="additions" aria-atomic="false">{(snapshot.liveTranscript??[]).slice(-30).map(segment=><p key={segment.id}>{segment.text}</p>)}{liveCaptions?.turns.filter(turn=>!(snapshot.liveTranscript??[]).some(segment=>segment.providerItemId===turn.id)).slice(-8).map(turn=><p key={turn.id}>{turn.text}<small> · {liveCaptions.persistedTurnIds.includes(turn.id)?'Saved; syncing replay':'Saving to class replay'}</small></p>)}</div>{liveCaptions?.interim?<p aria-live="off">{liveCaptions.interim}</p>:snapshot.interimTranscript?.map(segment=>segment.expiresAt>Date.now()/1000?<p key={segment.id} aria-live="off">{segment.text}</p>:null)}</section>:null}
        {snapshot.recording.captureInterrupted?<p>Capture was interrupted. Saved audio can be recovered; the final moments may be missing.</p>:null}
        {snapshot.recording.error||snapshot.recording.chunks.failed?<p role="alert">{snapshot.recording.error||'Some audio slices could not be transcribed.'}<Button size="sm" variant="outline" onClick={()=>void actionRouter.dispatch({type:'open-note',noteId:snapshot.session.noteId})}>Open recording recovery</Button></p>:null}
        {snapshot.session.noSpeech?<p>No transcribed speech is available for a revision package. Review the saved recording and its transcription status.</p>:null}
        {snapshot.session.sourceCorrected?<p>Transcript wording was corrected. Updated study material appears here; saved note edits and existing quiz answers are preserved.</p>:null}
        {snapshot.recording.captureComplete&&snapshot.recording.chunks.missing.length?<p>Missing audio slices: {snapshot.recording.chunks.missing.join(', ')}. Full completion waits for recovery.<Button size="sm" variant="outline" onClick={()=>void command('partial_package')}>Prepare available coverage</Button></p>:null}
        {view==='notes'?<><details ref={transcriptDetailsRef} data-font-scale={policy.transcriptFontScale} onToggle={event=>{if(event.currentTarget.open&&!policy.autoScrollLock&&!cueNavigationPending.current)window.requestAnimationFrame(()=>transcriptEndRef.current?.scrollIntoView({block:'nearest'}));}}><summary>Transcript · {snapshot.transcript.length} passages loaded</summary><div className={styles.transcriptBody}>{snapshot.transcript.map(segment=><p id={`class-transcript-${segment.id}`} tabIndex={-1} key={segment.id}><small>{formatCueTime(segment.startMs)}</small> {segment.normalizedText||segment.rawText}</p>)}<div ref={transcriptEndRef}/></div>{snapshot.transcriptHasMore?<Button size="sm" variant="outline" disabled={transcriptPageBusy} onClick={()=>void loadMoreTranscript()}>{transcriptPageBusy?'Loading transcript…':'Load more transcript'}</Button>:null}</details>{outputs.filter(o=>o.kind==='notes').map(output)}<Button size="sm" variant="outline" onClick={()=>void actionRouter.dispatch({type:'open-note',noteId:snapshot.session.noteId})}>Open saved class note</Button></>:null}
        {view==='materials'?outputs.filter(o=>o.kind==='materials').map(output):null}
        {view==='practice'?outputs.filter(o=>['practice','flashcards'].includes(o.kind)).map(output):null}
        {view==='package'?<>{outputs.filter(o=>['summary','recall','revision_quiz'].includes(o.kind)).map(output)}{!snapshot.recording.captureComplete?<p>Summary, revision quiz and active recall are prepared after you stop.</p>:null}</>:null}
        {snapshot.outputHasMore?<Button size="sm" variant="outline" disabled={outputPageBusy} onClick={()=>void loadMoreOutputs()}>{outputPageBusy?'Loading earlier results…':'Load earlier class results'}</Button>:null}
        {!outputs.length?<p>Waiting for settled speech. Notes and practice appear quietly as coverage arrives.</p>:null}
      </div>
      {reference&&referenceOpen?<aside className={styles.referencePane} aria-label="Class reference" onKeyDown={event=>{if(event.key==='Escape'){event.preventDefault();setReferenceOpen(false);if(referenceOpener.current?.isConnected)referenceOpener.current.focus();else document.querySelector<HTMLButtonElement>('[aria-label="Class views"] button[aria-pressed="true"]')?.focus();}}}>
        <header><div><small>COURSE REFERENCE · PAGE {shownReferenceLabel}{shownReferenceLabel!==String(shownReferencePage+1)?` · PDF PAGE ${shownReferencePage+1}`:''}</small><h3>{reference.title}</h3></div><button type="button" aria-label="Close reference" onClick={()=>{setReferenceOpen(false);if(referenceOpener.current?.isConnected)referenceOpener.current.focus();else document.querySelector<HTMLButtonElement>('[aria-label="Class views"] button[aria-pressed="true"]')?.focus();}}>×</button></header>
        {activeReferenceManifest?.outline.length?<details className={styles.referenceOutline}><summary>Document contents</summary><nav aria-label="PDF contents">{activeReferenceManifest.outline.map((entry,index)=><button key={`${entry.pageIndex}:${index}`} type="button" onClick={()=>setReferencePageIndex(entry.pageIndex)} style={{paddingInlineStart:`${8+Math.min(entry.depth,10)*12}px`}}><span>{entry.title}</span><small>{entry.pageLabel}</small></button>)}</nav></details>:null}
        {referencePdfSource&&referencePdfSource.classId===classId&&referencePdfSource.versionId===reference.versionId?<><ClassPdfReader source={{url:referencePdfSource.url,httpHeaders:referencePdfSource.httpHeaders}} pageIndex={shownReferencePage} pageCount={activeReferenceManifest?.pageCount||0} geometry={shownReferencePage===reference.pageIndex?reference.geometry:null} onPageChange={setReferencePageIndex}/><button className={styles.openPdf} type="button" onClick={()=>void openReferencePdf()}>Open full PDF in a new tab</button></>:null}
        {referencePdfState==='loading'?<small role="status">Loading the original PDF…</small>:null}
        {referencePdfState==='unavailable'?<small role="status">The original PDF is not available here. The extracted passage is shown below.</small>:null}
        {activeReferenceManifest?.indexProgress?<small role="status">Page indexing: {Object.entries(activeReferenceManifest.indexProgress.pages).map(([state,count])=>`${count} ${state.replaceAll('_',' ')}`).join(' · ')}. Background OCR: {Object.entries(activeReferenceManifest.indexProgress.ocrWork).map(([state,count])=>`${count} ${state.replaceAll('_',' ')}`).join(' · ')||'No pending OCR work'}.</small>:null}
        {activeReferenceManifest?.ocrDeferredPageCount?<small className={styles.referenceCitationPage}>OCR was limited for {activeReferenceManifest.ocrDeferredPageCount} pages; some scanned text may be missing.</small>:null}
        {activeReferenceManifest?.ocrStatus==='disabled'||activeReferenceManifest?.ocrStatus==='unavailable'?<small className={styles.referenceCitationPage}>Scanned pages may not have searchable text.</small>:null}
        {shownReferencePage!==reference.pageIndex?<small className={styles.referenceCitationPage}>The extracted passage below cites page {reference.pageLabel||reference.pageIndex+1}.</small>:null}
        {reference.extractionStatus==='ocr_extracted_estimated'?<small className={styles.referenceCitationPage}>OCR text{reference.ocrConfidence!==null&&reference.ocrConfidence!==undefined?` · ${Math.round(reference.ocrConfidence)}% confidence`:''}. Check the wording against the original page.</small>:null}
        <div className={styles.referenceText}>{reference.text}</div>
        <small>Supplementary material. Check the original source for full context.</small>
        <Button size="sm" variant="outline" onClick={()=>void actionRouter.dispatch({type:'open-source',source:reference})}>Open in Sources</Button>
      </aside>:null}
    </div>
    <details className={styles.diagnostics} onToggle={event=>{if(!event.currentTarget.open||classMetrics?.classId===classId||classMetricsBusy)return;setClassMetricsBusy(true);setClassMetricsError('');void classApi.metrics(classId).then(value=>{if(activeClassIdRef.current===classId)setClassMetrics(value);}).catch(cause=>{if(activeClassIdRef.current===classId)setClassMetricsError(cause instanceof Error?cause.message:'Could not load processing diagnostics.');}).finally(()=>setClassMetricsBusy(false));}}>
      <summary>Processing diagnostics</summary>
      <p>Latency percentiles use completed samples for this class. Missing values mean no sample is available.</p>
      {classMetricsBusy?<small role="status">Loading class metrics…</small>:null}
      {classMetricsError?<small role="alert">{classMetricsError}</small>:null}
      {classMetrics?.classId===classId?Object.entries(classMetrics.stages).map(([stage,values])=><article key={stage}>
        <strong>{stage.replaceAll('_',' ')}</strong>
        <small>Queue p50/p90: {values.queueWaitP50Ms===null?'—':`${Math.round(values.queueWaitP50Ms)} ms`} / {values.queueWaitP90Ms===null?'—':`${Math.round(values.queueWaitP90Ms)} ms`}</small>
        <small>Run p50/p90: {values.runP50Ms===null?'—':`${Math.round(values.runP50Ms)} ms`} / {values.runP90Ms===null?'—':`${Math.round(values.runP90Ms)} ms`}</small>
        <small>End-to-end p50/p90: {values.endToEndP50Ms===null?'—':`${Math.round(values.endToEndP50Ms)} ms`} / {values.endToEndP90Ms===null?'—':`${Math.round(values.endToEndP90Ms)} ms`} · {values.sampleCount} samples</small>
      </article>):null}
    </details>
    <footer><Button variant="ghost" size="sm" disabled={snapshot.session.outputTransitionPending} onClick={()=>void command(snapshot.session.cancelled?'resume_processing':'cancel_processing')}>{snapshot.session.cancelled?'Resume processing':'Pause processing'}</Button><small>{snapshot.session.outputTransitionPending?'Updating class outputs…':'This control does not stop audio capture.'}</small></footer>
  </section>;
}
