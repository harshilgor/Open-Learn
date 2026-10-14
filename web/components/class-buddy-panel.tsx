"use client";
import {useEffect,useRef,useState} from 'react';
import {GenerationStream} from '@/lib/generation-stream';
import {classBuddyApi,getClassQuestionContext,CLASS_BUDDY_REQUEST_EVENT,CLASS_EVIDENCE_OPEN_EVENT,type ClassAnswerEvidence,type ClassQuestionContext} from '@/lib/class-buddy';
import {Button} from './ui/button';
import {RichContent} from './rich-content';

type Question={id:string;question:string;answer:string;generationId?:string;evidence?:ClassAnswerEvidence;status:string};
export function ClassBuddyPanel({classId,sessionId,anchorMs,buddyName='Buddy',version=0}:{classId:string;sessionId:string;anchorMs:number;buddyName?:string;version?:number}){
  const [draft,setDraft]=useState(''),[questions,setQuestions]=useState<Question[]>([]),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const [selection,setSelection]=useState<ClassQuestionContext|null>(null),[doubts,setDoubts]=useState<Awaited<ReturnType<typeof classBuddyApi.doubts>>['items']>([]);
  const scope=useRef(classId);scope.current=classId;
  const stream=useRef<GenerationStream|null>(null),input=useRef<HTMLTextAreaElement>(null);
  useEffect(()=>{
    setQuestions([]);setDraft('');setSelection(null);setBusy(false);setError('');
    let live=true;
    void classBuddyApi.history(classId).then(value=>{if(live)setQuestions(current=>[...value.items,...current.filter(question=>!value.items.some(saved=>saved.generationId===question.generationId))].slice(-20));}).catch(()=>undefined);
    void classBuddyApi.doubts(classId).then(value=>{if(live)setDoubts(value.items);}).catch(()=>undefined);
    const receive=(event:Event)=>{const detail=(event as CustomEvent<{context:ClassQuestionContext;message:string}>).detail;if(detail?.context.classId!==classId)return;setSelection(detail.context);setDraft(detail.message);input.current?.focus();};
    window.addEventListener(CLASS_BUDDY_REQUEST_EVENT,receive);
    return()=>{live=false;stream.current?.disconnect();window.removeEventListener(CLASS_BUDDY_REQUEST_EVENT,receive);};
  },[classId]);
  useEffect(()=>{let active=true;void classBuddyApi.history(classId).then(value=>{if(!active)return;setQuestions(current=>{const known=new Set(current.map(question=>question.generationId).filter(Boolean));return [...value.items.filter(saved=>!known.has(saved.generationId)),...current.map(question=>{const saved=value.items.find(value=>value.generationId===question.generationId);return saved?{...question,evidence:saved.evidence,answer:question.answer||saved.answer,status:saved.status==='completed'?'Answered':question.status}:question;})].slice(-20);});}).catch(()=>undefined);return()=>{active=false;};},[classId,version]);
  async function send(message=draft,context=selection||getClassQuestionContext(sessionId)||{classId,anchorMs}){
    if(!message.trim()||busy)return;
    const id=crypto.randomUUID(),expectedScope=classId,observer=new GenerationStream();stream.current=observer;
    setQuestions(current=>[...current,{id,question:message,answer:'',status:'Connecting'}].slice(-20));setBusy(true);setError('');setDraft('');setSelection(null);
    try{
      await observer.start(sessionId,{action:'message',mode:'ask',presentation:'conversation',gear:'Quick',expectedRevision:1,message,clientMessageId:id,classContext:context},{
        onDescriptor:descriptor=>{if(scope.current!==expectedScope)return;setQuestions(current=>current.map(question=>question.id===id?{...question,generationId:descriptor.id||undefined,status:'Answering'}:question));if(descriptor.id)void classBuddyApi.evidence(expectedScope,descriptor.id).then(evidence=>{if(scope.current===expectedScope)setQuestions(current=>current.map(question=>question.id===id?{...question,evidence}:question));}).catch(()=>undefined);},
        onEvent:event=>{if(scope.current!==expectedScope)return;const delta=typeof event.data.delta==='string'?event.data.delta:typeof event.data.text==='string'?event.data.text:'';if(event.type==='text.delta')setQuestions(current=>current.map(question=>question.id===id?{...question,answer:question.answer+delta}:question));if(['generation.completed','generation.cancelled','generation.interrupted','generation.error'].includes(event.type))setQuestions(current=>current.map(question=>question.id===id?{...question,status:event.type==='generation.completed'?'Answered':event.type==='generation.cancelled'?'Stopped':event.type==='generation.interrupted'?'Interrupted':'Failed'}:question));if(event.type==='generation.error')setError('Buddy could not finish this response. Your question is saved in the class conversation.');},
      });
    }catch(cause){if(scope.current===expectedScope){setError(cause instanceof Error?cause.message:'Buddy could not answer.');setQuestions(current=>current.map(question=>question.id===id?{...question,status:'Failed'}:question));}}
    finally{if(scope.current===expectedScope)setBusy(false);}
  }
  async function lost(){
    const moment=getClassQuestionContext(sessionId)?.anchorMs??anchorMs,question="I'm lost. Explain the current idea briefly and identify what I need to understand first.";
    try{await classBuddyApi.saveDoubt(classId,moment,question);setDoubts((await classBuddyApi.doubts(classId)).items);await send(question,{classId,anchorMs:moment});}catch(cause){setError(String(cause));}
  }
  async function save(){try{await classBuddyApi.saveDoubt(classId,selection?.anchorMs??anchorMs,draft);setDoubts((await classBuddyApi.doubts(classId)).items);setDraft('');}catch(cause){setError(String(cause));}}
  return <aside aria-label="Class Buddy" className="class-buddy-panel">
    <h3>{buddyName} · Class questions</h3><p>Ask quietly. Answers use the lecture moment captured when you submit.</p>
    <div><Button size="sm" variant="outline" disabled={busy} onClick={()=>void send('Explain what was just said in this class.')}>Explain that</Button><Button size="sm" variant="outline" disabled={busy} onClick={()=>void send('I missed the last minute. Recap it briefly.')}>Last minute</Button><Button size="sm" disabled={busy} onClick={()=>void lost()}>I’m lost</Button></div>
    <form onSubmit={event=>{event.preventDefault();void send();}}><label>Ask {buddyName}<textarea ref={input} value={draft} maxLength={4000} onChange={event=>setDraft(event.currentTarget.value)} placeholder="Why does this step follow?"/></label><Button type="submit" disabled={busy||!draft.trim()}>Ask</Button><Button type="button" variant="outline" disabled={!draft.trim()} onClick={()=>void save()}>Save doubt for later</Button></form>
    {busy?<Button variant="ghost" onClick={()=>void stream.current?.stop()}>Stop Buddy response</Button>:null}
    {error?<p role="alert">{error}</p>:null}
    <div aria-live="off">{questions.map(question=><article key={question.id}><strong>{question.question}</strong><small> · {question.status}</small><RichContent body={question.answer} classEvidence={{segmentIds:question.evidence?.evidence.map(source=>source.segmentId)||[],onOpen:segmentId=>window.dispatchEvent(new CustomEvent(CLASS_EVIDENCE_OPEN_EVENT,{detail:{classId,segmentId}}))}}/>{question.evidence?<details><summary>Lecture evidence · {Math.floor(question.evidence.anchorMs/1000)}s</summary>{question.evidence.needsReview?<div><p>This answer used earlier transcript wording. Review the corrected passages.</p><Button size="sm" disabled={busy} onClick={()=>void send(question.question,{classId,anchorMs:question.evidence!.anchorMs})}>Ask again with corrected evidence</Button></div>:null}{question.evidence.availableThroughMs<question.evidence.anchorMs?<p>Transcript available through {Math.floor(question.evidence.availableThroughMs/1000)}s when you asked.</p>:null}{question.evidence.selectedNotes?.map(note=><blockquote key={note.blockId}><strong>{note.title} · {note.studentEdited?'Student note':'Generated note'} · revision {note.revision}</strong><p>{note.body}</p></blockquote>)}{question.evidence.evidence.map(source=><blockquote key={source.segmentId}><Button size="sm" variant="ghost" onClick={()=>window.dispatchEvent(new CustomEvent(CLASS_EVIDENCE_OPEN_EVENT,{detail:{classId,segmentId:source.segmentId}}))}>{Math.floor(source.startMs/1000)}s · revision {source.revision}</Button><p>{source.text}</p><small>Speaker: {source.speakerRole}{source.confidence!==null?` · Recognition confidence ${Math.round(source.confidence*100)}%`:''}</small></blockquote>)}</details>:null}</article>)}</div>
    <details><summary>Saved doubts ({doubts.filter(doubt=>doubt.resolution!=='resolved').length})</summary>{doubts.map(doubt=><div key={doubt.id}><p>{Math.floor(doubt.anchorMs/1000)}s · {doubt.question}</p><Button size="sm" variant="outline" onClick={()=>{setDraft(doubt.question);setSelection({classId,anchorMs:doubt.anchorMs});input.current?.focus();}}>Ask about this moment</Button><Button size="sm" variant="ghost" onClick={()=>void classBuddyApi.resolve(classId,doubt,doubt.resolution==='resolved'?'open':'resolved').then(()=>classBuddyApi.doubts(classId)).then(value=>setDoubts(value.items)).catch(cause=>setError(String(cause)))}>{doubt.resolution==='resolved'?'Reopen':'Mark resolved'}</Button></div>)}</details>
  </aside>;
}
