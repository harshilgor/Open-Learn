"use client";
import { useEffect,useRef,useState } from 'react';
import { classApi,type ClassSnapshot,type ClassOutput } from '@/lib/in-class';
import {openWorkspaceSource,openWorkspaceQuiz,openWorkspaceNote,openWorkspaceFlashcards} from '@/lib/workspace-events';
import {useBuddies,BuddyAvatar} from './buddies';
import {RichContent} from './rich-content';
import {Button} from './ui/button';
import styles from './in-class-workspace.module.css';

export function InClassWorkspace({classId}:{classId:string|null}){
  const buddies=useBuddies();
  const [snapshot,setSnapshot]=useState<ClassSnapshot|null>(null);
  const [view,setView]=useState('notes');const [error,setError]=useState('');
  const [revealed,setRevealed]=useState<Record<string,boolean>>({});
  const cursor=useRef(0),requestEpoch=useRef(0);
  useEffect(()=>{
    if(!classId)return;let live=true;let pending=false;const epoch=++requestEpoch.current;cursor.current=0;
    const load=async()=>{if(pending)return;pending=true;try{const next=await classApi.snapshot(classId,cursor.current);if(!live||requestEpoch.current!==epoch)return;cursor.current=next.cursor;setSnapshot(current=>current?.session.id===next.session.id&&current.cursor>next.cursor?current:next);setError('');}catch(cause){if(live)setError(cause instanceof Error?cause.message:'Connection interrupted. Saved output stays available.');}finally{pending=false;}};
    void load();const timer=setInterval(()=>void load(),3000);return()=>{live=false;clearInterval(timer);};
  },[classId]);
  if(!classId)return <div className={styles.empty}>Start a class session from your course or the conversation mode menu.</div>;
  if(!snapshot||snapshot.session.id!==classId)return <div className={styles.empty} role="status">{error||'Connecting to your class… Audio saved on this device continues uploading when connected.'}</div>;
  const outputs=snapshot.outputs;
  async function command(action:string,outputId?:string){try{const next=await classApi.command(classId!,snapshot!.session.revision,action,outputId);cursor.current=Math.max(cursor.current,next.cursor);setSnapshot(next);setError('');}catch(cause){setError(cause instanceof Error?cause.message:'Could not update processing.');}}
  function citations(ids:string[],key:string){return <><button type="button" onClick={()=>setRevealed(current=>({...current,[key]:!current[key]}))}>{revealed[key]?'Hide lecture evidence':'Show lecture evidence'}</button>{revealed[key]?snapshot!.transcript.filter(segment=>ids.includes(segment.id)).map(segment=><blockquote key={segment.id}><small>{Math.floor(segment.startMs/1000)}–{Math.floor(segment.endMs/1000)}s</small>{segment.normalizedText||segment.rawText}</blockquote>):null}</>;}
  function output(item:ClassOutput){
    if(item.status!=='ready')return <div key={item.id} className={styles.output} role="status"><strong>{item.kind.replaceAll('_',' ')}</strong><p>{item.error||'Preparing quietly…'}</p>{item.status==='failed'?<Button size="sm" variant="outline" onClick={()=>void command('retry',item.id)}>Retry this output</Button>:null}</div>;
    const result=item.result;
    return <section key={item.id} className={styles.output}>
      {item.kind==='flashcards' && result?.deckId?<Button onClick={()=>openWorkspaceFlashcards({deckId:result.deckId,view:'editor'})}>Open draft deck</Button>:null}
      {result?.blocks?.map((block,index)=><div key={index}><h3>{block.title}</h3><RichContent body={block.body}/><small>Lecture evidence: {block.segmentIds.length} passages · {item.kind==='notes'?(snapshot!.recording.captureComplete?'Generated note':'Live draft'):'Generated summary'}</small>{citations(block.segmentIds,item.id+':evidence:'+index)}</div>)}
      {result?.sources?.map(source=><button className={styles.source} type="button" key={source.spanId} onClick={()=>openWorkspaceSource(source)}><strong>{source.title} · Page {source.pageIndex+1}</strong><p>{source.text.slice(0,500)}</p><small>Supporting material · supplementary to the lecture</small></button>)}
      {item.kind==='materials'&&!result?.sources?.length?<p>No matching passage in the selected materials yet.</p>:null}
      {result?.items?.map((card,index)=>{const key=item.id+':'+index;return <div key={key} className={styles.card}><RichContent body={card.prompt}/>{revealed[key]?<RichContent body={card.answer}/>:null}<button type="button" onClick={()=>setRevealed(current=>({...current,[key]:!current[key]}))}>{revealed[key]?'Hide answer':'Reveal answer'}</button><small>{item.kind==='flashcards'?'Draft card · not scheduled for review':'Active recall'} · {card.segmentIds.length} lecture passages</small>{citations(card.segmentIds,key+':evidence')}</div>;})}
      {result?.quizId?<><p>{item.kind==='revision_quiz'?'Revision quiz':'Practice the material covered so far'}</p><Button size="sm" onClick={()=>openWorkspaceQuiz({sessionId:snapshot!.session.sessionId,origin:'ask',quizId:result.quizId})}>Open quiz</Button><small>Questions and feedback use the shared quiz experience.</small></>:null}
      {result?.boundedCoverage?<p>Coverage is limited to a bounded selection of this class.</p>:null}
    </section>;
  }
  return <section className={styles.workspace} aria-label="In-Class workspace">
    <header>{buddies.snapshot?.profiles.filter(buddy=>buddy.id===snapshot.session.buddyId).map(buddy=><div key={buddy.id}><BuddyAvatar buddy={buddy}/><strong>{buddy.name}</strong></div>)}<h2>{snapshot.session.title}</h2><p>{snapshot.session.processing.replaceAll('-',' ')} · {snapshot.recording.captureComplete?'Capture stopped':'Capture remains on its recording device'} · {snapshot.recording.chunks.transcribed} slices transcribed</p><small>Recording controls stay in the workspace shell. Opening this class never starts a microphone.</small></header>
    <nav aria-label="Class views" className={styles.tabs}>{['notes','materials','practice','package'].map(tab=><button type="button" aria-pressed={view===tab} key={tab} onClick={()=>setView(tab)}>{tab==='package'?'Revision':tab[0].toUpperCase()+tab.slice(1)}{tab==='practice'?` (${outputs.filter(o=>['practice','flashcards'].includes(o.kind)&&o.status==='ready').length})`:''}</button>)}</nav>
    {error?<p role="alert">{error}</p>:null}
    {snapshot.recording.captureInterrupted?<p>Capture was interrupted. Saved audio can be recovered; the final moments may be missing.</p>:null}
    {snapshot.recording.error||snapshot.recording.chunks.failed?<p role="alert">{snapshot.recording.error||'Some audio slices could not be transcribed.'}<Button size="sm" variant="outline" onClick={()=>openWorkspaceNote(snapshot.session.noteId)}>Open recording recovery</Button></p>:null}
    {snapshot.session.noSpeech?<p>No transcribed speech is available for a revision package. Review the saved recording and its transcription status.</p>:null}
    {snapshot.session.sourceCorrected?<p>Transcript wording was corrected. Updated study material appears here; saved note edits and existing quiz answers are preserved.</p>:null}
    {snapshot.recording.captureComplete&&snapshot.recording.chunks.missing.length?<p>Missing audio slices: {snapshot.recording.chunks.missing.join(', ')}. Full completion waits for recovery.<Button size="sm" variant="outline" onClick={()=>void command('partial_package')}>Prepare available coverage</Button></p>:null}
    {view==='notes'?<><details><summary>Transcript · {snapshot.transcript.length} passages</summary>{snapshot.transcript.map(segment=><p key={segment.id}><small>{Math.floor(segment.startMs/1000)}s</small> {segment.normalizedText||segment.rawText}</p>)}</details>{outputs.filter(o=>o.kind==='notes').map(output)}<Button size="sm" variant="outline" onClick={()=>openWorkspaceNote(snapshot.session.noteId)}>Open saved class note</Button></>:null}
    {view==='materials'?outputs.filter(o=>o.kind==='materials').map(output):null}
    {view==='practice'?outputs.filter(o=>['practice','flashcards'].includes(o.kind)).map(output):null}
    {view==='package'?<>{outputs.filter(o=>['summary','recall','revision_quiz'].includes(o.kind)).map(output)}{!snapshot.recording.captureComplete?<p>Summary, revision quiz and active recall are prepared after you stop.</p>:null}</>:null}
    {!outputs.length?<p>Waiting for settled speech. Notes and practice appear quietly as coverage arrives.</p>:null}
    <footer><Button variant="ghost" size="sm" onClick={()=>void command(snapshot.session.cancelled?'resume_processing':'cancel_processing')}>{snapshot.session.cancelled?'Resume processing':'Pause processing'}</Button><small>This control does not stop audio capture.</small></footer>
  </section>;
}
