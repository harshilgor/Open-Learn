"use client";
import {useEffect,useRef,useState} from 'react';
import {request,authenticatedResource,type LectureTranscriptSegment} from '@/lib/api';
import {authenticatedFetch} from '@/lib/account-session';
import {askClassBuddy} from '@/lib/class-buddy';
import {Button} from './ui/button';
export function ClassTranscriptPassage({classId,segment,onCorrected}:{classId:string;segment:LectureTranscriptSegment&{normalizationVersion?:number};onCorrected:(value:{segmentId:string;wording:string;speakerRole:string;revision:number})=>void}){
  const [editing,setEditing]=useState(false),[wording,setWording]=useState(''),[speaker,setSpeaker]=useState('unknown'),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const [audio,setAudio]=useState<{url:string;startSeconds:number;endSeconds:number}|null>(null),source=useRef<string|null>(null);
  const base=`/v1/class-sessions/${encodeURIComponent(classId)}/transcript/${encodeURIComponent(segment.id)}`;
  useEffect(()=>()=>{if(source.current)URL.revokeObjectURL(source.current);},[base]);
  async function correct(undo=false){setBusy(true);try{const saved=await request<{segmentId:string;wording:string;speakerRole:string;revision:number}>(`${base}${undo?`/undo?revision=${segment.normalizationVersion||1}`:''}`,{method:undo?'POST':'PATCH',...(undo?{}:{body:JSON.stringify({expectedRevision:segment.normalizationVersion||1,wording,speakerRole:speaker})})});setEditing(false);onCorrected(saved);}catch(cause){setError(String(cause));}finally{setBusy(false);}}
  async function replay(){setBusy(true);try{const info=await request<{startSeconds:number;endSeconds:number}>(base+'/audio-info');const resource=await authenticatedResource(base+'/audio');const response=await authenticatedFetch(resource.url,{headers:resource.httpHeaders});if(!response.ok)throw Error('Retained audio is unavailable for this passage.');const blob=await response.blob();if(source.current)URL.revokeObjectURL(source.current);const url=URL.createObjectURL(blob);source.current=url;setAudio({url,...info});}catch(cause){setError(String(cause));}finally{setBusy(false);}}
  return <div><small>{Math.floor(segment.startMs/60000)}:{String(Math.floor(segment.startMs/1000)%60).padStart(2,'0')} · {segment.speaker==='unknown'?'Speaker unknown':segment.speaker}{(segment.normalizationVersion||1)>1?' · Student corrected':segment.confidence==null?' · Confidence unavailable':segment.confidence<.8?' · Check uncertain wording':''}</small><p>{segment.normalizedText||segment.rawText}</p>
    <Button size="sm" variant="ghost" disabled={busy} onClick={()=>void replay()}>Replay passage</Button><Button size="sm" variant="ghost" disabled={busy} onClick={()=>{setEditing(true);setWording(segment.normalizedText||segment.rawText);setSpeaker(segment.speaker);}}>Correct wording or speaker</Button><Button size="sm" variant="ghost" onClick={()=>askClassBuddy({classId,anchorMs:segment.endMs,segmentRefs:[{segmentId:segment.id,revision:segment.normalizationVersion||1}],review:true},'Explain this lecture passage briefly.')}>Ask Buddy</Button>
    {(segment.normalizationVersion||1)>1?<Button size="sm" variant="ghost" disabled={busy} onClick={()=>void correct(true)}>Undo last correction</Button>:null}
    {editing?<form onSubmit={event=>{event.preventDefault();void correct();}}><label>Corrected wording<textarea value={wording} maxLength={4000} rows={4} onChange={event=>setWording(event.target.value)}/></label><label>Identify speaker<select value={speaker} onChange={event=>setSpeaker(event.target.value)}><option value="unknown">Unknown</option><option value="professor">Professor</option><option value="student">Student</option></select></label><Button disabled={busy||!wording.trim()} type="submit">Save correction</Button><Button type="button" variant="ghost" onClick={()=>setEditing(false)}>Cancel</Button></form>:null}
    {audio?<audio controls src={audio.url} aria-label="Replay lecture passage" onLoadedMetadata={event=>{event.currentTarget.currentTime=audio.startSeconds;}} onTimeUpdate={event=>{if(event.currentTarget.currentTime>=audio.endSeconds)event.currentTarget.pause();}}/>:null}
    {error?<p role="alert">{error}</p>:null}
  </div>;
}
