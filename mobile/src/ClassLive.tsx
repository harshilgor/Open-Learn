import {useCallback,useEffect,useRef,useState} from 'react';
import {AppState,Pressable,Text,View} from 'react-native';
import {api,account,authenticatedEventStream} from './account';
import {styles} from './theme';

type ClassSummary={id:string;sessionId:string;title:string;courseId:string|null;createdAt:number;processing:string;recordingStatus:string;capturing:boolean};
type Reference={title:string;text:string;pageIndex:number};
type ClassOutput={id:string;windowId:string;windowStartMs?:number;kind:string;status:string;revision:number;provisional?:boolean;settlement?:string;error?:string;result?:{blocks?:{title:string;body:string}[];items?:{prompt:string;answer:string}[];sources?:Reference[];summary?:string;body?:string;questions?:string[]}};
type ClassOutputPage={items:ClassOutput[];hasMore:boolean;nextCursor:string|null;generation:number};
type ClassSnapshot={provisionalNotes?:{id:string;status:string;result:{blocks?:{title:string;body:string}[]}}[];session:{id:string;title:string;courseId:string|null;processing:string;partial:boolean;cancelled:boolean;needInfo?:{id:string;status:string;prompt:string;query:string}[]};recording:{captureComplete:boolean;captureInterrupted?:boolean};outputs:ClassOutput[];outputHasMore?:boolean;outputCursor?:string|null;outputGeneration?:number;cursor:number;hasMore:boolean;events:{id:string;cursor:number;type:string;data:Record<string,unknown>}[];delta?:boolean;outputsReset?:boolean};
const groupTitle:Record<string,string>={notes:'Live notes',materials:'Materials',practice:'Practice',flashcards:'Flashcards',summary:'Summary',recall:'Active recall',revision_quiz:'Revision quiz'};
function merge(current:ClassSnapshot|null,next:ClassSnapshot):ClassSnapshot{
  if(!next.delta||!current||current.session.id!==next.session.id)return next;
  const outputs=new Map<string,ClassOutput>(next.outputsReset?[]:current.outputs.map(output=>[output.id,output] as const));
  for(const output of next.outputs){const previous=outputs.get(output.id);if(!previous||output.revision>=previous.revision)outputs.set(output.id,output);}
  return {...next,outputs:[...outputs.values()].sort((a,b)=>(a.windowStartMs??0)-(b.windowStartMs??0)||a.id.localeCompare(b.id)),outputHasMore:next.outputsReset?next.outputHasMore:current.outputHasMore,outputCursor:next.outputsReset?next.outputCursor:current.outputCursor,outputGeneration:next.outputsReset?next.outputGeneration:current.outputGeneration};
}

export function ClassLive({owner,requestedClass}:{owner:string;requestedClass?:string|null}){
  const [classes,setClasses]=useState<ClassSummary[]>([]),[classCursor,setClassCursor]=useState<string|null>(null),[loadingMoreClasses,setLoadingMoreClasses]=useState(false),[selected,setSelected]=useState<ClassSummary|null>(null),[snapshot,setSnapshot]=useState<ClassSnapshot|null>(null),[loading,setLoading]=useState(true),[snapshotLoading,setSnapshotLoading]=useState(false),[outputPageBusy,setOutputPageBusy]=useState(false),[error,setError]=useState(''),[retry,setRetry]=useState(0);
  const cursor=useRef(0),lastEventId=useRef<string|undefined>(undefined),listGeneration=useRef(0),snapshotGeneration=useRef(0),snapshotRef=useRef<ClassSnapshot|null>(null),classesRef=useRef<ClassSummary|null>(selected);
  snapshotRef.current=snapshot;classesRef.current=selected;
  useEffect(()=>{if(!requestedClass)return;let alive=true;void api.json<ClassSnapshot>(`/v1/class-sessions/${encodeURIComponent(requestedClass)}`).then(value=>{if(alive&&account()?.owner===owner)setSelected({id:value.session.id,sessionId:'',title:value.session.title,courseId:value.session.courseId,createdAt:Date.now()/1000,processing:value.session.processing,recordingStatus:'',capturing:!value.recording.captureComplete});}).catch(cause=>{if(alive)setError(String(cause));});return()=>{alive=false;};},[requestedClass,owner]);
  const refreshList=useCallback(async()=>{
    const version=++listGeneration.current;setLoading(true);setError('');
    try{const result=await api.json<{items:ClassSummary[];nextCursor:string|null}>('/v1/class-sessions?limit=30');if(version!==listGeneration.current||account()?.owner!==owner)return;setClasses(result.items);setClassCursor(result.nextCursor);setSelected(current=>current?result.items.find(item=>item.id===current.id)||null:null);}
    catch(cause){if(version===listGeneration.current&&account()?.owner===owner)setError(cause instanceof Error?cause.message:'Could not load recent classes.');}
    finally{if(version===listGeneration.current)setLoading(false);}
  },[owner]);
  const loadOlderClasses=useCallback(async()=>{
    if(!classCursor||loadingMoreClasses||loading)return;const generation=listGeneration.current;setLoadingMoreClasses(true);
    try{const result=await api.json<{items:ClassSummary[];nextCursor:string|null}>(`/v1/class-sessions?limit=30&cursor=${encodeURIComponent(classCursor)}`);if(generation!==listGeneration.current||account()?.owner!==owner)return;setClasses(current=>[...current,...result.items]);setClassCursor(result.nextCursor);}
    catch(cause){setError(cause instanceof Error?cause.message:'Could not load older classes.');}
    finally{setLoadingMoreClasses(false);}
  },[classCursor,loading,loadingMoreClasses,owner]);
  useEffect(()=>{if(selected)return;void refreshList();const timer=setInterval(()=>void refreshList(),30000);return()=>{listGeneration.current++;clearInterval(timer);};},[refreshList,selected?.id]);

  useEffect(()=>{
    const currentClass=selected;if(!currentClass){setSnapshot(null);setSnapshotLoading(false);return;}
    const version=++snapshotGeneration.current;let alive=true,pending=false,fallbackPolling=false,streamController:AbortController|undefined,fallbackTimer:ReturnType<typeof setInterval>|undefined;let combined:ClassSnapshot|null=null;let eventQueue=Promise.resolve();cursor.current=0;lastEventId.current=undefined;setSnapshot(null);setSnapshotLoading(true);setError('');
    const valid=()=>alive&&version===snapshotGeneration.current&&classesRef.current?.id===currentClass.id&&account()?.owner===owner;
    const apply=(next:ClassSnapshot,eventId?:string)=>{
      if(!valid())return;
      if(next.delta&&next.cursor<cursor.current)return;
      const existing=combined?.session.id===currentClass.id?combined:snapshotRef.current?.session.id===currentClass.id?snapshotRef.current:null;
      combined=merge(existing,next);cursor.current=next.cursor;
      const lastEvent=next.events[next.events.length-1]?.id;lastEventId.current=eventId||lastEvent||lastEventId.current;
      setSnapshot(combined);setSnapshotLoading(false);setError('');
    };
    const consumeSnapshot=async(next:ClassSnapshot,eventId?:string)=>{
      apply(next,eventId);
      for(let page=0;next.hasMore&&page<10&&valid();page++){
        next=await api.json<ClassSnapshot>(`/v1/class-sessions/${encodeURIComponent(currentClass.id)}/events?cursor=${cursor.current}&initialized=true`);
        if(!valid())return;
        apply(next);
      }
    };
    const load=async()=>{
      if(pending||!valid())return;pending=true;
      try{
        let next:ClassSnapshot;
        if(!combined&&(!snapshotRef.current||snapshotRef.current.session.id!==currentClass.id))next=await api.json<ClassSnapshot>(`/v1/class-sessions/${encodeURIComponent(currentClass.id)}?cursor=0&initialized=false`);
        else next=await api.json<ClassSnapshot>(`/v1/class-sessions/${encodeURIComponent(currentClass.id)}/events?cursor=${cursor.current}&initialized=true`);
        if(!valid())return;
        await consumeSnapshot(next);
      }catch(cause){if(valid()){setSnapshotLoading(false);setError(cause instanceof Error?cause.message:'Could not sync this class.');}}
      finally{pending=false;}
    };
    const stream=async()=>{
      let retryDelay=1000;
      while(valid()){
        if(!combined&&!snapshotRef.current)await load();
        if(!valid())return;
        const controller=new AbortController();streamController=controller;let lastStreamActivity=Date.now();
        const streamWatchdog=setInterval(()=>{if(Date.now()-lastStreamActivity>30000){fallbackPolling=true;controller.abort();}},5000);
        try{
          await authenticatedEventStream(`/v1/class-sessions/${encodeURIComponent(currentClass.id)}/stream?cursor=${cursor.current}&initialized=true`,{
            lastEventId:lastEventId.current,signal:controller.signal,
            onActivity:()=>{lastStreamActivity=Date.now();if(valid())setError('');},
            onEvent:event=>{
              if(event.event!=='class.snapshot'||!valid())return;
              let next:ClassSnapshot;try{next=JSON.parse(event.data) as ClassSnapshot;}catch{void load();return;}
              eventQueue=eventQueue.then(()=>consumeSnapshot(next,event.id)).catch(cause=>{if(valid())setError(cause instanceof Error?cause.message:'Could not sync this class.');});
            },
          });
          retryDelay=1000;
        }catch(cause){
          if(!valid())return;
          if(controller.signal.aborted&&!fallbackPolling)return;
          if(cause instanceof Error&&'status'in cause&&((cause as {status:number}).status===404||(cause as {status:number}).status===405||(cause as {status:number}).status===501)){
            fallbackPolling=true;
            if(!fallbackTimer)fallbackTimer=setInterval(()=>void load(),3000);
          }else{
            if(!fallbackPolling){await eventQueue;if(valid())setError(cause instanceof Error?cause.message:'Class stream disconnected; reconnecting.');}
          }
        }finally{clearInterval(streamWatchdog);if(streamController===controller)streamController=undefined;}
        if(fallbackPolling){if(!fallbackTimer)fallbackTimer=setInterval(()=>void load(),3000);await load();return;}
        await new Promise(resolve=>setTimeout(resolve,retryDelay));retryDelay=Math.min(15000,retryDelay*2);
      }
    };
    void stream();const appState=AppState.addEventListener('change',state=>{if(state==='active')void load();});
    return()=>{alive=false;streamController?.abort();if(fallbackTimer)clearInterval(fallbackTimer);appState.remove();};
  },[selected,owner,retry]);

  const open=(item:ClassSummary)=>{snapshotGeneration.current++;setSelected(item);setSnapshot(null);cursor.current=0;};
  const outputs=snapshot?.outputs||[];
  const loadOlderOutputs=useCallback(async()=>{
    const current=snapshotRef.current;
    if(!selected||!current?.outputHasMore||!current.outputCursor||outputPageBusy)return;
    const selectedId=selected.id,generation=snapshotGeneration.current,outputGeneration=current.outputGeneration;
    setOutputPageBusy(true);
    try{
      const page=await api.json<ClassOutputPage>(`/v1/class-sessions/${encodeURIComponent(selectedId)}/outputs?cursor=${encodeURIComponent(current.outputCursor)}`);
      if(generation!==snapshotGeneration.current||classesRef.current?.id!==selectedId||account()?.owner!==owner)return;
      if(page.generation!==outputGeneration){setSnapshot(null);setRetry(value=>value+1);return;}
      setSnapshot(previous=>{
        if(!previous||previous.session.id!==selectedId||previous.outputGeneration!==outputGeneration)return previous;
        const merged=new Map(previous.outputs.map(output=>[output.id,output] as const));
        for(const output of page.items){const existing=merged.get(output.id);if(!existing||output.revision>=existing.revision)merged.set(output.id,output);}
        return {...previous,outputs:[...merged.values()].sort((a,b)=>(a.windowStartMs??0)-(b.windowStartMs??0)||a.id.localeCompare(b.id)),outputHasMore:page.hasMore,outputCursor:page.nextCursor};
      });
      setError('');
    }catch(cause){
      if(generation===snapshotGeneration.current&&classesRef.current?.id===selectedId){setError(cause instanceof Error?cause.message:'Could not load earlier class outputs.');setSnapshot(null);setRetry(value=>value+1);}
    }finally{setOutputPageBusy(false);}
  },[outputPageBusy,owner,selected]);
  return <View style={{gap:12}}>
    {selected?<>
      <Pressable accessibilityRole="button" onPress={()=>{snapshotGeneration.current++;setSelected(null);setSnapshot(null);}}><Text style={styles.link}>‹ Recent classes</Text></Pressable>
      <Text style={styles.title}>{selected.title}</Text><Text style={styles.muted}>{snapshot?(snapshot.recording.captureComplete?'Capture stopped':'Capture remains on its recording device'):selected.capturing?'Capture is live':selected.recordingStatus==='completed'?'Capture complete':'Capture stopped'}{snapshot?.session.partial?' · Partial coverage':''} · {snapshot?.session.processing||selected.processing}</Text>
      {snapshotLoading&&!snapshot?<Text style={styles.muted}>Opening current class state…</Text>:null}
      {!snapshot&&error?<Pressable accessibilityRole="button" onPress={()=>{setError('');setRetry(value=>value+1);}}><Text style={styles.error}>{error} · Tap to retry.</Text></Pressable>:null}
      {snapshot?.provisionalNotes?.filter(note=>note.status!=='reconciled').map(note=><View key={note.id} style={styles.card}><Text accessibilityRole="header" style={styles.heading}>Provisional live notes</Text><Text style={styles.muted}>{note.status==='unmatched'?'No authoritative audio match · Unverified':note.status==='failed'?'Preparation failed':note.status==='preparing'?'Preparing from live captions':'Awaiting authoritative transcript'}</Text>{note.result.blocks?.map((block,index)=><View key={`${note.id}:${index}`}><Text style={styles.heading}>{block.title}</Text><Text style={styles.text}>{block.body}</Text></View>)}</View>)}
      {snapshot?(['notes','materials','practice','flashcards','summary','recall','revision_quiz'] as const).map(kind=>{
        const entries=outputs.filter(output=>output.kind===kind),needs=kind==='materials'?snapshot.session.needInfo?.filter(need=>need.status==='open')||[]:[];if(!entries.length&&!needs.length)return null;
        return <View key={kind} style={styles.card}><Text style={styles.heading}>{groupTitle[kind]}</Text>{needs.map(need=><View key={need.id}><Text style={styles.muted}>Source needed</Text><Text style={styles.text}>{need.prompt}</Text></View>)}{entries.map(output=><View key={output.id} style={{gap:7,borderTopWidth:1,borderTopColor:'#343743',paddingTop:9}}><Text style={styles.muted}>{output.provisional?'Provisional · Awaiting authoritative transcript':output.settlement==='partial'?'Partial transcript coverage':output.status==='ready'?'Ready':output.status==='failed'?'Needs attention':output.status==='paused'?'Paused':'Preparing'}</Text>
          {output.result?.blocks?.map((block,index)=><View key={`${output.id}-b-${index}`}><Text style={styles.heading}>{block.title}</Text><Text style={styles.text}>{block.body}</Text></View>)}
          {output.result?.sources?.map((source,index)=><View key={`${output.id}-s-${index}`}><Text style={styles.heading}>{source.title} · page {source.pageIndex+1}</Text><Text style={styles.text}>{source.text}</Text></View>)}
          {output.result?.items?.map((item,index)=><View key={`${output.id}-i-${index}`}><Text style={styles.text}>{item.prompt}</Text></View>)}
          {output.result?.summary?<Text style={styles.text}>{output.result.summary}</Text>:null}
          {output.result?.body?<Text style={styles.text}>{output.result.body}</Text>:null}
          {output.result?.questions?.map((question,index)=><Text style={styles.text} key={`${output.id}-q-${index}`}>{question}</Text>)}
          {output.status==='failed'?<Text style={styles.muted}>This item did not finish. Open the class in Open Learn to review it.</Text>:null}
        </View>)}</View>;
      }):null}
      {snapshot&&!outputs.length?<View style={styles.card}><Text style={styles.text}>No class outputs are ready yet. This view will update as the class progresses.</Text></View>:null}
      {snapshot?.outputHasMore?<Pressable accessibilityRole="button" disabled={outputPageBusy} onPress={()=>void loadOlderOutputs()}><Text style={styles.link}>{outputPageBusy?'Loading earlier results…':'Load earlier class results'}</Text></Pressable>:null}
      {error?<Text accessibilityRole="alert" style={styles.error}>Sync paused: {error}</Text>:null}
      <Text style={styles.muted}>Updates sync automatically. Control this phone’s microphone from the capture panel. Classes recorded on other devices can be followed here.</Text>
    </>:<>
      <Text style={styles.title}>Recent classes</Text><Text style={styles.muted}>Follow live notes and class outputs.</Text>
      {loading&&!classes.length?<Text style={styles.muted}>Loading classes…</Text>:null}
      {error&&!classes.length?<Text accessibilityRole="alert" style={styles.error}>{error}</Text>:null}
      {classes.map(item=><Pressable accessibilityRole="button" style={styles.card} key={item.id} onPress={()=>open(item)}><Text style={styles.heading}>{item.title}</Text><Text style={styles.muted}>{item.capturing?'Live now':item.recordingStatus==='completed'?'Capture complete':'Stopped'} · {new Date(item.createdAt*1000).toLocaleString()}</Text><Text style={styles.muted}>{item.processing}</Text></Pressable>)}
      {!loading&&!classes.length&&!error?<View style={styles.card}><Text style={styles.text}>No class sessions yet. Start a class from the capture panel.</Text></View>:null}
      {error&&classes.length?<Pressable accessibilityRole="button" onPress={()=>void refreshList()}><Text style={styles.error}>{error} · Tap to retry.</Text></Pressable>:null}
      {classCursor?<Pressable accessibilityRole="button" disabled={loadingMoreClasses} onPress={()=>void loadOlderClasses()}><Text style={styles.link}>{loadingMoreClasses?'Loading older classes…':'Load older classes'}</Text></Pressable>:null}
      <Pressable accessibilityRole="button" onPress={()=>void refreshList()}><Text style={styles.link}>Refresh classes</Text></Pressable>
    </>}
  </View>;
}
