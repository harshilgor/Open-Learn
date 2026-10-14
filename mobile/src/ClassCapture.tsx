import {useEffect,useRef,useState} from 'react';
import {AccessibilityInfo,Alert,AppState,Pressable,Text,TextInput,View} from 'react-native';
import {account,api} from './account';
import {deleteLocalRecording,recordings,saveRecording,startRecording,updateRecording,uploadRecording,claimPhoneClass,startPairedRecording,reportCapture,acknowledgeCapture,previewPhoneClass,finishPhonePairing,type PhonePairPreview} from './recordings';
import type {Recording} from './protocol';
import {styles} from './theme';
import {startPhoneCaptions} from './class-stream';
import {ApiError} from './protocol';
import {ClassBuddy} from './ClassBuddy';
import {checkPhoneMicrophone} from './microphone-check';

// Mounted at account scope so opening another screen never starts or stops a microphone.
export function ClassCapture({owner,visible,courses,onOpen,pairingCode}:{owner:string;visible:boolean;courses:{id:string;name:string}[];onOpen:(id:string)=>void;pairingCode?:string}){
  const [record,setRecord]=useState<Recording|null>(null),[title,setTitle]=useState('Class'),[course,setCourse]=useState(''),[consent,setConsent]=useState(false),[busy,setBusy]=useState(false),[restoring,setRestoring]=useState(true),[error,setError]=useState('');
  const [inputCheck,setInputCheck]=useState('');const checkController=useRef<AbortController|null>(null);
  useEffect(()=>()=>checkController.current?.abort(),[]);
  const current=useRef<Recording|null>(null),locked=useRef(false);
  const [processing,setProcessing]=useState('');
  const [pairCode,setPairCode]=useState(pairingCode||'');const promptedResume=useRef(new Set<string>());
  const [pairPreview,setPairPreview]=useState<PhonePairPreview|null>(null);
  const pairScope=useRef('');pairScope.current=owner+':'+pairCode;
  const [phoneBattery,setPhoneBattery]=useState<number|null>(null);
  useEffect(()=>{setPairPreview(null);setConsent(false);},[pairCode,owner]);
  useEffect(()=>{if(pairingCode)setPairCode(pairingCode);},[pairingCode]);
  const captureState=record?(record.stopped?'Stopped':record.paused?'Paused':'Recording'):null;
  const [captionStatus,setCaptionStatus]=useState('');
  useEffect(()=>{if(record?.classSetup?.speechQuality==='economical'){setCaptionStatus('Economical mode · saved audio verification; live captions off.');return;}if(!record?.classSetup?.runId||record.stopped||record.paused)return;return startPhoneCaptions(()=>current.current!,setCaptionStatus);},[record?.classSetup?.runId,record?.classSetup?.speechQuality,record?.stopped,record?.paused]);
  useEffect(()=>{if(captureState)AccessibilityInfo.announceForAccessibility(`Class microphone ${captureState.toLowerCase()}.`);},[captureState]);
  const apply=(value:Recording)=>{current.current=value;setRecord({...value});};
  async function run(action:()=>Promise<void>){if(locked.current||account()?.owner!==owner)return;locked.current=true;setBusy(true);try{await action();setError('');}catch(cause){setError(cause instanceof Error?cause.message:'Capture could not continue.');}finally{locked.current=false;setBusy(false);}}
  async function sync(){
    const value=current.current;
    if(value){
      let latest=value.stopped?value:await updateRecording(value,'inspect');apply(latest);
      if(latest.classSetup?.runId){
        let status:Awaited<ReturnType<typeof reportCapture>>;
        try{status=await reportCapture(latest);setPhoneBattery(status.batteryPercent);}catch(cause){
          if(cause instanceof ApiError&&cause.status===409&&!latest.stopped){
            latest=await updateRecording(latest,'stop');
            latest.classSetup={...latest.classSetup!,finalizeOnStop:false};
            await saveRecording(latest);apply(latest);await uploadRecording(latest);
          }
          throw cause;
        }
        for(const command of status.commands){
          if(command.action==='resume'&&latest.paused){
            if(!promptedResume.current.has(command.id)){
              promptedResume.current.add(command.id);
              Alert.alert('Resume class microphone?','Your laptop requested recording to resume. Confirm on this phone.',[
                {text:'Keep paused',style:'cancel',onPress:()=>void run(async()=>{if(current.current)await acknowledgeCapture(current.current,command.id,false);})},
                {text:'Resume',onPress:()=>void run(async()=>{if(!current.current)return;if(command.expiresAt<=Date.now()/1000){await acknowledgeCapture(current.current,command.id,false);throw Error('Resume request expired. Request again from the laptop.');}const resumed=await updateRecording(current.current,'resume');apply(resumed);await acknowledgeCapture(resumed,command.id,true);})},
              ]);
            }
            continue;
          }
          if(command.action==='pause'&&!latest.paused&&!latest.stopped)latest=await updateRecording(latest,'pause');
          if(['stop','handoff'].includes(command.action)){
            if(!latest.stopped)latest=await updateRecording(latest,'stop');
            latest.classSetup={...latest.classSetup!,finalizeOnStop:command.action==='stop'};await saveRecording(latest);
          }
          apply(latest);await acknowledgeCapture(latest,command.id,true);
        }
      }
      await uploadRecording(latest);
      if(account()?.owner===owner){apply(latest);const state=await api.json<{recordingStatus:string;chunks:{transcribed:number;serverConfirmed:number}}>(`/v1/learners/${encodeURIComponent(owner)}/lecture-recordings/${latest.id}`);setProcessing(`${state.recordingStatus} · ${state.chunks.transcribed}/${state.chunks.serverConfirmed} slices transcribed`);}
    }
    for(const saved of await recordings(owner)){if(saved.classSetup&&saved.stopped&&!saved.finalized&&(saved.id!==value?.id||saved.classSetup.runId!==value?.classSetup?.runId))await uploadRecording(saved);}
  }
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
      <Text style={styles.text}>{captureState} · Captured {Math.floor(record.durationMs/60000)}:{String(Math.floor(record.durationMs/1000)%60).padStart(2,'0')} · {record.segments.filter(s=>s.acknowledged).length}/{record.segments.length} slices uploaded{phoneBattery!==null?` · Battery ${phoneBattery}%`:''}{record.finalized?' · Audio finalized':''}</Text>
      {processing?<Text style={styles.muted}>{processing}</Text>:null}
      {captionStatus?<Text accessibilityLiveRegion="polite" style={styles.muted}>{captionStatus}</Text>:null}
      {visible&&record.classSetup?.classId?<ClassBuddy classId={record.classSetup.classId} anchorMs={(record.classSetup.startMs||0)+record.durationMs}/>:null}
      {record.interrupted?<Text style={styles.muted}>Capture contains an interruption or pause gap. Saved audio is retained and coverage is marked partial. An OS-stopped capture needs a new class to record more.</Text>:null}
      {!record.stopped?<>{button(record.paused?'Resume microphone':'Pause microphone',async()=>{apply(await updateRecording(current.current!,current.current!.paused?'resume':'pause'));})}
        {button('Mark this moment',async()=>{const latest=await updateRecording(current.current!,'inspect');latest.markersMs=[...(latest.markersMs||[]),latest.durationMs].slice(-500);await saveRecording(latest);apply(latest);})}
        {button('Stop microphone',async()=>{const stopped=await updateRecording(current.current!,'stop');if(stopped.classSetup?.runId)stopped.classSetup.finalizeOnStop=true;await saveRecording(stopped);apply(stopped);await uploadRecording(stopped);apply(stopped);})}</>:null}
      {button('Retry saved audio upload',sync)}
      <Pressable accessibilityRole="button" onPress={()=>onOpen('class_'+record.id)}><Text style={styles.link}>Open live class notes</Text></Pressable>
      {record.finalized?<Pressable accessibilityRole="button" disabled={busy} onPress={()=>Alert.alert('Delete local class audio?','Uploaded audio and notes remain in Open Learn. This removes this phone’s saved WAV files.',[{text:'Keep audio',style:'cancel'},{text:'Delete local audio',style:'destructive',onPress:()=>void run(async()=>{await deleteLocalRecording(record);current.current=null;setRecord(null);setConsent(false);})}])}><Text style={styles.link}>Delete local audio</Text></Pressable>:null}
      {record.stopped?button('Set up another class',async()=>{apply(record);current.current=null;setRecord(null);setConsent(false);}):null}
    </>:<>
      <Text accessibilityRole="header" style={styles.heading}>Use this phone for a laptop class</Text>
      <TextInput accessibilityLabel="Laptop class pairing code" style={styles.input} value={pairCode} onChangeText={setPairCode} editable={!busy} autoCapitalize="characters" maxLength={80}/>
      <Text style={styles.muted}>Enter the code shown on your laptop to preview the class. Previewing does not access the microphone.</Text>
      {button('Preview laptop class',async()=>{const scope=pairScope.current;const preview=await previewPhoneClass(owner,pairCode.trim());if(account()?.owner!==owner||scope!==pairScope.current)return;setPairPreview(preview);setConsent(false);},pairCode.trim().replace(/[ -]/g,'').length<12)}
      {pairPreview?<View accessibilityLabel="Class pairing preview"><Text style={styles.heading}>{pairPreview.title}</Text><Text style={styles.text}>Account: {account()?.name||owner}</Text><Text style={styles.text}>Requested by: {pairPreview.requestingDeviceName} · {pairPreview.requestingDeviceId.slice(-12)}</Text><Text style={styles.muted}>Confirm this is the class and laptop you intend to record for. The pairing expires at {new Date(pairPreview.expiresAt*1000).toLocaleTimeString()}.</Text></View>:null}
      <Pressable accessibilityRole="checkbox" accessibilityState={{checked:consent}} onPress={()=>setConsent(value=>!value)}><Text style={styles.link}>{consent?'☑':'☐'} I have permission to record this class</Text></Pressable>
      <Text style={styles.muted}>{inputCheck||'Check microphone input for five seconds. The short local sample is deleted and never uploaded.'}</Text>
      {button('Check phone microphone input',async()=>{if(!consent)throw Error('Confirm permission before checking the microphone.');const controller=new AbortController();checkController.current=controller;setInputCheck('Speak normally for five seconds.');try{setInputCheck(await checkPhoneMicrophone(controller.signal));}finally{checkController.current=null;}},!consent)}
      {button('Confirm pairing and start recording',async()=>{if(!pairPreview||pairPreview.ownerId!==owner)throw Error('Preview this class before recording.');const claim=await claimPhoneClass(owner,pairCode.trim(),consent);if(claim.classId!==pairPreview.classId)throw Error('The class changed. Preview it again.');const value=await startPairedRecording(owner,claim);apply(value);await finishPhonePairing(owner,pairCode.trim()).catch(()=>undefined);setPairCode('');setPairPreview(null);onOpen(claim.classId);},!consent||!pairPreview)}
      {pairPreview?button('Cancel pairing preview',async()=>{setPairPreview(null);setConsent(false);}):null}
      <TextInput accessibilityLabel="Class recording title" style={styles.input} value={title} onChangeText={setTitle} maxLength={240}/>
      <View style={styles.row}><Pressable accessibilityRole="button" accessibilityState={{selected:course===''}} onPress={()=>setCourse('')}><Text style={styles.link}>{course===''?'✓ ':''}General</Text></Pressable>{courses.map(item=><Pressable key={item.id} accessibilityRole="button" accessibilityState={{selected:course===item.id}} onPress={()=>setCourse(item.id)}><Text style={styles.link}>{course===item.id?'✓ ':''}{item.name}</Text></Pressable>)}</View>
      <Text style={styles.muted}>With consent, your microphone audio is saved privately on this device and uploaded to Open Learn for transcription and notes. Local audio remains until you delete the saved recording. Background capture depends on your phone; interruptions are shown when you return.</Text>
      <Pressable accessibilityRole="checkbox" accessibilityState={{checked:consent}} onPress={()=>setConsent(value=>!value)}><Text style={styles.link}>{consent?'☑':'☐'} I have permission to record this class</Text></Pressable>
      {button('Start class microphone',async()=>{const value=await startRecording(owner,course,title.trim(),true);apply(value);await uploadRecording(value);apply(value);},!consent||!title.trim())}
    </>}
    {error?<Text accessibilityRole="alert" style={styles.error}>{error} Saved audio is retained; retry when connected.</Text>:null}
  </View>;
}
