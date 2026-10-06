import {useEffect,useRef,useState} from 'react';
import {AccessibilityInfo,Alert,AppState,Pressable,Text,TextInput,View} from 'react-native';
import {account,api} from './account';
import {deleteLocalRecording,recordings,saveRecording,startRecording,updateRecording,uploadRecording} from './recordings';
import type {Recording} from './protocol';
import {styles} from './theme';

// Mounted at account scope so opening another screen never starts or stops a microphone.
export function ClassCapture({owner,visible,courses,onOpen}:{owner:string;visible:boolean;courses:{id:string;name:string}[];onOpen:(id:string)=>void}){
  const [record,setRecord]=useState<Recording|null>(null),[title,setTitle]=useState('Class'),[course,setCourse]=useState(''),[consent,setConsent]=useState(false),[busy,setBusy]=useState(false),[restoring,setRestoring]=useState(true),[error,setError]=useState('');
  const current=useRef<Recording|null>(null),locked=useRef(false);
  const [processing,setProcessing]=useState('');
  const captureState=record?(record.stopped?'Stopped':record.paused?'Paused':'Recording'):null;
  useEffect(()=>{if(captureState)AccessibilityInfo.announceForAccessibility(`Class microphone ${captureState.toLowerCase()}.`);},[captureState]);
  const apply=(value:Recording)=>{current.current=value;setRecord({...value});};
  async function run(action:()=>Promise<void>){if(locked.current||account()?.owner!==owner)return;locked.current=true;setBusy(true);try{await action();setError('');}catch(cause){setError(cause instanceof Error?cause.message:'Capture could not continue.');}finally{locked.current=false;setBusy(false);}}
  async function sync(){const value=current.current;if(value){const latest=value.stopped?value:await updateRecording(value,'inspect');apply(latest);await uploadRecording(latest);if(account()?.owner===owner){apply(latest);const state=await api.json<{recordingStatus:string;chunks:{transcribed:number;serverConfirmed:number}}>(`/v1/learners/${encodeURIComponent(owner)}/lecture-recordings/${latest.id}`);setProcessing(`${state.recordingStatus} · ${state.chunks.transcribed}/${state.chunks.serverConfirmed} slices transcribed`);}}for(const saved of await recordings(owner)){if(saved.classSetup&&saved.stopped&&!saved.finalized&&saved.id!==value?.id)await uploadRecording(saved);}}
  useEffect(()=>{
    let alive=true;
    void recordings(owner).then(async items=>{const saved=items.filter(item=>item.classSetup&&!item.finalized).sort((a,b)=>b.startedAtMs-a.startedAtMs)[0];if(!saved||!alive)return;try{const value=saved.stopped?saved:await updateRecording(saved,'inspect');if(alive)apply(value);}catch(cause){if(alive)setError(String(cause));}}).catch(cause=>{if(alive)setError(String(cause));}).finally(()=>{if(alive)setRestoring(false);});
    const timer=setInterval(()=>void run(sync),5000);
    const listener=AppState.addEventListener('change',state=>{if(state==='active')void run(sync);});
    return()=>{alive=false;clearInterval(timer);listener.remove();};
  },[owner]);
  if(!visible&&!record)return null;
  const button=(label:string,action:()=>Promise<void>,disabled=false)=><Pressable accessibilityRole="button" accessibilityState={{disabled:busy||disabled||restoring}} disabled={busy||disabled||restoring} style={styles.button} onPress={()=>void run(action)}><Text style={styles.buttonText}>{label}</Text></Pressable>;
  return <View style={styles.card}>
    <Text accessibilityRole="header" style={styles.heading}>Class microphone capture</Text>
    {restoring?<Text style={styles.muted}>Checking saved class audio…</Text>:null}
    {record?<>
      <Text style={styles.text}>{captureState} · {Math.floor(record.durationMs/1000)} seconds · {record.segments.filter(s=>s.acknowledged).length}/{record.segments.length} slices uploaded{record.finalized?' · Audio finalized':''}</Text>
      {processing?<Text style={styles.muted}>{processing}</Text>:null}
      {record.interrupted?<Text style={styles.muted}>Capture contains an interruption or pause gap. Saved audio is retained and coverage is marked partial. An OS-stopped capture needs a new class to record more.</Text>:null}
      {!record.stopped?<>{button(record.paused?'Resume microphone':'Pause microphone',async()=>{apply(await updateRecording(current.current!,current.current!.paused?'resume':'pause'));})}
        {button('Mark this moment',async()=>{const latest=await updateRecording(current.current!,'inspect');latest.markersMs=[...(latest.markersMs||[]),latest.durationMs].slice(-500);await saveRecording(latest);apply(latest);})}
        {button('Stop microphone',async()=>{const stopped=await updateRecording(current.current!,'stop');apply(stopped);await uploadRecording(stopped);apply(stopped);})}</>:null}
      {button('Retry saved audio upload',sync)}
      <Pressable accessibilityRole="button" onPress={()=>onOpen('class_'+record.id)}><Text style={styles.link}>Open live class notes</Text></Pressable>
      {record.finalized?<Pressable accessibilityRole="button" disabled={busy} onPress={()=>Alert.alert('Delete local class audio?','Uploaded audio and notes remain in Open Learn. This removes this phone’s saved WAV files.',[{text:'Keep audio',style:'cancel'},{text:'Delete local audio',style:'destructive',onPress:()=>void run(async()=>{await deleteLocalRecording(record);current.current=null;setRecord(null);setConsent(false);})}])}><Text style={styles.link}>Delete local audio</Text></Pressable>:null}
      {record.stopped?button('Set up another class',async()=>{apply(record);current.current=null;setRecord(null);setConsent(false);}):null}
    </>:<>
      <TextInput accessibilityLabel="Class recording title" style={styles.input} value={title} onChangeText={setTitle} maxLength={240}/>
      <View style={styles.row}><Pressable accessibilityRole="button" accessibilityState={{selected:course===''}} onPress={()=>setCourse('')}><Text style={styles.link}>{course===''?'✓ ':''}General</Text></Pressable>{courses.map(item=><Pressable key={item.id} accessibilityRole="button" accessibilityState={{selected:course===item.id}} onPress={()=>setCourse(item.id)}><Text style={styles.link}>{course===item.id?'✓ ':''}{item.name}</Text></Pressable>)}</View>
      <Text style={styles.muted}>With consent, your microphone audio is saved privately on this device and uploaded to Open Learn for transcription and notes. Local audio remains until you delete the saved recording. Background capture depends on your phone; interruptions are shown when you return.</Text>
      <Pressable accessibilityRole="checkbox" accessibilityState={{checked:consent}} onPress={()=>setConsent(value=>!value)}><Text style={styles.link}>{consent?'☑':'☐'} I have permission to record this class</Text></Pressable>
      {button('Start class microphone',async()=>{const value=await startRecording(owner,course,title.trim(),true);apply(value);await uploadRecording(value);apply(value);},!consent||!title.trim())}
    </>}
    {error?<Text accessibilityRole="alert" style={styles.error}>{error} Saved audio is retained; retry when connected.</Text>:null}
  </View>;
}
