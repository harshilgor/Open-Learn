import {useEffect,useRef,useState} from 'react';
import {Button,Text,TextInput,View} from 'react-native';
import * as Crypto from 'expo-crypto';
import {api,authenticatedEventStream} from './account';
import {styles} from './theme';

export function ClassBuddy({classId,anchorMs}:{classId:string;anchorMs:number}){
  const [question,setQuestion]=useState(''),[answer,setAnswer]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const [evidence,setEvidence]=useState<{anchorMs:number;availableThroughMs:number;needsReview:boolean;evidence:{segmentId:string;text:string;startMs:number}[]}|null>(null);
  const controller=useRef<AbortController|null>(null),scope=useRef(classId);scope.current=classId;
  useEffect(()=>{setAnswer('');setEvidence(null);setBusy(false);return()=>controller.current?.abort();},[classId]);
  async function ask(value=question){
    if(busy||!value.trim())return;
    const expected=classId,moment=anchorMs,key=Crypto.randomUUID(),abort=new AbortController();controller.current=abort;
    setBusy(true);setError('');setAnswer('');setEvidence(null);
    try{
      const snapshot=await api.json<{session:{sessionId:string}}>(`/v1/class-sessions/${encodeURIComponent(expected)}`);
      if(abort.signal.aborted)return;
      const descriptor=await api.json<{id?:string;status:string}>(`/v1/sessions/${encodeURIComponent(snapshot.session.sessionId)}/generations`,{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':key},body:JSON.stringify({expectedRevision:1,action:'message',mode:'ask',gear:'Quick',message:value,clientMessageId:key,classContext:{classId:expected,anchorMs:moment}})});
      if(!descriptor.id)throw Error('Open the class conversation to select a Buddy response mode.');
      const frozen=await api.json<NonNullable<typeof evidence>>(`/v1/class-sessions/${encodeURIComponent(expected)}/buddy-contexts/by-generation/${encodeURIComponent(descriptor.id)}`);
      if(scope.current===expected)setEvidence(frozen);
      let cursor=0;
      for(let retry=0;retry<4&&!abort.signal.aborted;retry++){
        let terminal=false;
        try{await authenticatedEventStream(`/v1/generations/${encodeURIComponent(descriptor.id)}/events?after=${cursor}`,{signal:abort.signal,onEvent:frame=>{
          const event=JSON.parse(frame.data) as {sequence:number;type:string;data:{text?:string}};
          if(event.sequence<=cursor)return;cursor=event.sequence;
          if(scope.current!==expected)return;
          if(event.type==='text.delta')setAnswer(current=>current+(event.data.text||''));
          if(['generation.completed','generation.cancelled','generation.interrupted','generation.error'].includes(event.type)){terminal=true;abort.abort();if(event.type==='generation.error')setError('Buddy could not finish. The question remains in your class conversation.');}
        }});}catch(cause){if(!terminal&&!abort.signal.aborted&&retry===3)throw cause;}
        if(terminal||abort.signal.aborted)break;
      }
    }catch(cause){if(scope.current===expected&&!abort.signal.aborted)setError(cause instanceof Error?cause.message:'Buddy unavailable.');}
    finally{if(scope.current===expected)setBusy(false);}
  }
  async function saveDoubt(){try{await api.json(`/v1/class-sessions/${encodeURIComponent(classId)}/doubts`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({commandId:Crypto.randomUUID(),anchorMs,question})});setQuestion('');}catch(cause){setError(String(cause));}}
  return <View style={styles.card}><Text style={styles.heading}>Class Buddy</Text><Text style={styles.muted}>Quiet answers, anchored to the moment you ask.</Text><TextInput accessibilityLabel="Ask Class Buddy" style={styles.input} multiline maxLength={4000} value={question} onChangeText={setQuestion}/><Button title="Ask" disabled={busy||!question.trim()} onPress={()=>void ask()}/><Button title="Explain that" disabled={busy} onPress={()=>void ask('Explain the current lecture idea briefly.')}/><Button title="Save doubt for later" disabled={!question.trim()} onPress={()=>void saveDoubt()}/>{busy?<Button title="Close answer stream" onPress={()=>{controller.current?.abort();setBusy(false);}}/>:null}{answer?<Text selectable style={styles.text}>{answer}</Text>:null}{evidence?<><Text style={styles.muted}>Asked at {Math.floor(evidence.anchorMs/1000)}s · transcript through {Math.floor(evidence.availableThroughMs/1000)}s{evidence.needsReview?' · source needs review':''}</Text>{evidence.evidence.map(source=><Text selectable key={source.segmentId} style={styles.muted}>{Math.floor(source.startMs/1000)}s · {source.text}</Text>)}</>:null}{error?<Text accessibilityRole="alert" style={styles.error}>{error}</Text>:null}</View>;
}
