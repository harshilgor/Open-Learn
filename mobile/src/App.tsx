import {useCallback,useEffect,useRef,useState} from 'react';
import {AppState,KeyboardAvoidingView,Platform,Pressable,ScrollView,Text,TextInput,View,Linking,Alert} from 'react-native';
import {SafeAreaProvider,SafeAreaView} from 'react-native-safe-area-context';
import * as Crypto from 'expo-crypto';
import * as Notifications from 'expo-notifications';
import {account,api,restoreAccount,signIn,signOut} from './account';
import {journals} from './storage';
import {flushMessages,safeDeepLink,type PendingMessage,type Recording} from './protocol';
import {TaskCard,type Task} from './TaskCard';
import {recordings,startRecording,updateRecording,uploadRecording} from './recordings';
import {pickAndAttach,retryAttachment} from './files';
import {enablePush,disablePush,notificationLink} from './notifications';
import {VoiceMessage} from './VoiceMessage';
import {Responsibilities} from './Responsibilities';
import {LectureDetails} from './LectureDetails';
import type {CourseSummary,Message,JourneyCommand,SessionCreate} from './generated/api';
import {styles} from './theme';
type Conversation={id:string;title?:string;goal?:string;courseId?:string|null};
type Activity={id:string;sequence:number;text?:string;type:string};
type Journey={revision:number;turns:{question:string;lesson?:{blocks:{body:string}[]}}[]};
type Notice={id:string;title:string;url:string;status:string};
function Button({title,onPress,disabled=false}:{title:string;onPress:()=>void;disabled?:boolean}){return <Pressable accessibilityRole="button" disabled={disabled} onPress={onPress} style={[styles.button,{opacity:disabled?.5:1}]}><Text style={styles.buttonText}>{title}</Text></Pressable>}
export default function App(){return <SafeAreaProvider><SafeAreaView style={styles.screen}><Workspace/></SafeAreaView></SafeAreaProvider>}
function Workspace(){
  const [identity,setIdentity]=useState<ReturnType<typeof account>>(null),[sessions,setSessions]=useState<Conversation[]>([]),[courses,setCourses]=useState<CourseSummary[]>([]),[session,setSession]=useState<Conversation|null>(null),[course,setCourse]=useState<string|null>(null),[screen,setScreen]=useState<'chats'|'conversation'|'recordings'|'inbox'>('chats');
  const [tasks,setTasks]=useState<Task[]>([]),[activity,setActivity]=useState<Activity[]>([]),[journey,setJourney]=useState<Journey|null>(null),[pending,setPending]=useState<PendingMessage[]>([]),[records,setRecords]=useState<Recording[]>([]),[active,setActive]=useState<Recording|null>(null),[notices,setNotices]=useState<Notice[]>([]),[text,setText]=useState(''),[topic,setTopic]=useState(''),[mode,setMode]=useState<'ask'|'learn'|'research'|'sandbox_lab'>('ask'),[error,setError]=useState(''),[busy,setBusy]=useState(false),[pushEnabled,setPushEnabled]=useState(false);
  const [remoteRecords,setRemoteRecords]=useState<{id:string;title:string}[]>([]);
  const generation=useRef(0),syncing=useRef(false);
  const owner=identity?.owner;
  const refresh=useCallback(async()=>{
    if(!owner)return;const version=generation.current;
    const [chatList,courseList,recordList,inbox,remote]=await Promise.all([api.json<{sessions:Conversation[]}>('/v1/sessions'),api.json<CourseSummary[]>('/v1/courses'),recordings(owner),api.json<{notifications:Notice[]}>('/v1/assistant/responsibility-notifications'),api.json<{recordings:{id:string;title:string}[]}>(`/v1/learners/${owner}/lecture-recordings`)]);
    if(version!==generation.current)return;
    setSessions(chatList.sessions);setCourses(courseList);setRecords(recordList);setRemoteRecords(remote.recordings);setNotices(inbox.notifications);
    if(session){
      let cursor=0;const items:Activity[]=[];let latest:Task[]=[];
      for(let page=0;page<10;page++){
        const snapshot=await api.json<{cursor:number;hasMore:boolean;items:Activity[];tasks:Task[]}>(`/v1/assistant/sessions/${session.id}/activity?after=${cursor}`);
        items.push(...snapshot.items);latest=snapshot.tasks;cursor=snapshot.cursor;if(!snapshot.hasMore)break;
      }
      const [browser,learning]=await Promise.all([api.json<{tasks:Task[]}>(`/v1/assistant/tasks?sessionId=${session.id}`),api.json<Journey>(`/v1/sessions/${session.id}/journey`)]);
      if(version===generation.current){setActivity(items);setTasks([...latest,...browser.tasks]);setJourney(learning);}
    }
  },[owner,session]);
  async function run(action:()=>Promise<unknown>){const version=generation.current;setBusy(true);setError('');try{await action();if(version===generation.current)await refresh()}catch(cause){if(version===generation.current)setError(cause instanceof Error?cause.message:'Request failed.')}finally{if(version===generation.current)setBusy(false)}}
  async function sync(){
    if(!owner || syncing.current)return;syncing.current=true;
    const version=generation.current;try{const queue=await journals.read<PendingMessage[]>('messages:'+owner)||[];await flushMessages(owner,queue,api,()=>journals.write('messages:'+owner,queue));if(version!==generation.current)return;setPending([...queue]);await retryAttachment(owner,session?.courseId);await refresh();}
    finally{syncing.current=false}
  }
  useEffect(()=>{void restoreAccount().then(setIdentity).catch(cause=>setError(cause.message));},[]);
  useEffect(()=>{
    generation.current++;setBusy(false);if(!owner)return;const version=generation.current;
    void recordings(owner).then(value=>{if(version===generation.current)setRecords(value)});
    void journals.read<PendingMessage[]>('messages:'+owner).then(value=>{if(version===generation.current)setPending(value||[])});
    void journals.read<Conversation>('last-chat:'+owner).then(saved=>{if(saved && version===generation.current){setSession(saved);setScreen('conversation')}});
  },[owner]);
  useEffect(()=>{
    if(!owner)return;const version=generation.current;
    const tick=()=>void refresh().catch(cause=>{if(version===generation.current)setError(cause.message)});
    tick();const timer=setInterval(tick,5000);
    const listener=AppState.addEventListener('change',state=>{if(state==='active')void sync().catch(cause=>setError(cause.message))});
    return()=>{clearInterval(timer);listener.remove()};
    // Reconnect reads server snapshots; hosted workers continue with the app closed.
  },[refresh,owner]);
  useEffect(()=>{
    if(!owner)return;
    const open=(link:ReturnType<typeof safeDeepLink>)=>{if(!link || account()?.owner!==owner)return;const version=generation.current;void api.json<Conversation>(`/v1/sessions/${link.session}`).then(value=>{if(version!==generation.current)return;generation.current++;setBusy(false);setSession(value);setJourney(null);setTasks([]);setActivity([]);setScreen('conversation');}).catch(cause=>setError(cause.message));};
    void Linking.getInitialURL().then(url=>{if(url)open(safeDeepLink(url))});
    void Notifications.getLastNotificationResponseAsync().then(response=>{if(response)open(notificationLink(response))});
    const link=Linking.addEventListener('url',event=>open(safeDeepLink(event.url)));
    const push=Notifications.addNotificationResponseReceivedListener(response=>open(notificationLink(response)));
    return()=>{link.remove();push.remove()};
  },[owner]);
  async function send(task?:Task,request?:NonNullable<Task['pendingRequests']>[number],answer?:string){
    if(!owner||!session)return;const value=(answer||text).trim();if(!value)return;
    const id=Crypto.randomUUID();let body:Record<string,unknown>,path:string;
    if(task || mode==='research' || mode==='sandbox_lab'){
      const analysisInput=mode==='sandbox_lab'?await journals.read<string>('analysis-input:'+owner+':'+session.id):null;if(mode==='sandbox_lab' && !task && !analysisInput)throw Error('Attach your CSV before starting analysis.');
      const message:Message={...(analysisInput?{materialVersionId:analysisInput}:{}),schemaVersion:2,clientMessageId:id,sessionId:session.id,text:value,capability:task?null:mode as 'research'|'sandbox_lab',...(task&&request?{targetTaskId:task.id,replyToRequestId:request.requestId,expectedRevision:task.revision,expectedRequestRevision:request.revision}:{})};body=message;path='/v1/assistant/messages';
    }else{const command:JourneyCommand={expectedRevision:journey?.revision||1,action:'message',mode:mode as 'ask'|'learn',message:value};body=command;path=`/v1/sessions/${session.id}/journey`;}
    const queue=await journals.read<PendingMessage[]>('messages:'+owner)||[];queue.push({key:id,owner,path,body,state:'pending'});await journals.write('messages:'+owner,queue);setPending(queue);setText('');await sync();
  }
  async function openConversation(value:Conversation){generation.current++;setBusy(false);setSession(value);setJourney(null);setTasks([]);setActivity([]);setScreen('conversation');if(owner)await journals.write('last-chat:'+owner,value)}
  async function logout(){
    if(active){const stopped=await updateRecording(active,'stop');setActive(null);await saveLocal(stopped);}
    try{await disablePush()}catch{}
    generation.current++;await signOut();setIdentity(null);setSession(null);setSessions([]);setCourses([]);setTasks([]);setActivity([]);setJourney(null);setRecords([]);setRemoteRecords([]);setPending([]);setText('');setCourse(null);setNotices([]);setScreen('chats');setBusy(false);setPushEnabled(false);
  }
  async function saveLocal(record:Recording){setRecords(previous=>[...previous.filter(r=>r.id!==record.id),record]);}
  if(!identity)return <ScrollView contentContainerStyle={styles.scroll}><Text style={styles.title}>Open Learn</Text><Text style={styles.text}>Your conversations, courses, and ongoing work — wherever you learn.</Text><Button title="Sign in" disabled={busy} onPress={()=>void run(async()=>setIdentity(await signIn()))}/>{error?<Text accessibilityRole="alert" style={styles.error}>{error}</Text>:null}<Text style={styles.muted}>This native build needs a configured hosted API and account provider.</Text></ScrollView>;
  return <KeyboardAvoidingView style={styles.screen} behavior={Platform.OS==='ios'?'padding':undefined}><View style={[styles.row,{paddingHorizontal:18}]}>{(['chats','recordings','inbox'] as const).map(tab=><Pressable accessibilityRole="button" key={tab} onPress={()=>setScreen(tab)}><Text style={styles.link}>{tab==='chats'?'Chats':tab==='recordings'?'Recordings':'Inbox'}</Text></Pressable>)}<Pressable accessibilityRole="button" onPress={()=>void run(logout)}><Text style={styles.link}>Sign out</Text></Pressable></View>
    <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.scroll}>
      <Text style={styles.title}>{screen==='conversation'?session?.title||session?.goal||'Conversation':screen==='chats'?'Conversations':screen==='recordings'?'Record lecture':'Inbox'}</Text>
      {screen==='chats'?<><Text style={styles.muted}>{identity.name}</Text>{sessions.map(item=><Pressable accessibilityRole="button" style={styles.card} key={item.id} onPress={()=>void run(()=>openConversation(item))}><Text style={styles.heading}>{item.title||item.goal||'Conversation'}</Text></Pressable>)}<TextInput accessibilityLabel="New conversation topic" style={styles.input} placeholder="What would you like to learn?" placeholderTextColor="#a6abb8" value={topic} onChangeText={setTopic}/><Text style={styles.heading}>Course</Text><View style={styles.row}><Pressable accessibilityRole="button" onPress={()=>setCourse(null)}><Text style={styles.link}>General</Text></Pressable>{courses.map(item=><Pressable accessibilityRole="button" key={item.id} onPress={()=>setCourse(item.id)}><Text style={styles.link}>{course===item.id?'✓ ':''}{item.name}</Text></Pressable>)}</View><Button title="Start conversation" disabled={busy||!topic.trim()} onPress={()=>void run(async()=>{const body:SessionCreate={topic,goal:topic,courseId:course};const created=await api.json<Conversation>('/v1/sessions',{method:'POST',body:JSON.stringify(body)});await openConversation(created)})}/></>:null}
      {screen==='conversation' && session?<>
        {journey?.turns?.map((turn,index)=><View key={index} style={styles.card}><Text style={styles.heading}>{turn.question}</Text>{turn.lesson?.blocks?.map((block,i)=><Text key={i} style={styles.text}>{block.body}</Text>)}</View>)}
        {activity.filter(item=>item.text).map(item=><View key={item.id} style={item.type==='message.accepted'?styles.bubble:styles.card}><Text style={styles.text}>{item.text}</Text></View>)}
        {tasks.map(task=><TaskCard key={owner+task.id} task={task} run={action=>void run(action)} reply={(task,request,value)=>void run(()=>send(task,request,value))}/>)}
        {pending.filter(item=>item.body.sessionId===session.id||item.path===`/v1/sessions/${session.id}/journey`).map(item=><View key={item.key} style={styles.bubble}><Text style={styles.text}>{String(item.body.text||item.body.message)}</Text><Text style={styles.muted}>{item.state==='conflict'?'Needs review after a newer change':'Saved on phone · waiting to send'}</Text>{item.state==='conflict'?<Pressable accessibilityRole="button" onPress={()=>void run(async()=>{setText(String(item.body.text||item.body.message));const queue=pending.filter(p=>p.key!==item.key);await journals.write('messages:'+owner,queue);setPending(queue)})}><Text style={styles.link}>Review and resend</Text></Pressable>:null}</View>)}
        <View style={styles.row}>{(['ask','learn','research','sandbox_lab'] as const).map(value=><Pressable accessibilityRole="button" key={value} onPress={()=>setMode(value)}><Text style={styles.link}>{mode===value?'✓ ':''}{value==='sandbox_lab'?'Analyze':value.charAt(0).toUpperCase()+value.slice(1)}</Text></Pressable>)}</View>
        <TextInput accessibilityLabel="Message" style={styles.input} multiline placeholder="Message Open Learn" placeholderTextColor="#a6abb8" value={text} onChangeText={setText}/><Button title="Send" disabled={busy||!text.trim()} onPress={()=>void run(()=>send())}/>
        <View style={styles.row}><Pressable accessibilityRole="button" disabled={busy} onPress={()=>void run(()=>pickAndAttach(session.id,session.courseId))}><Text style={styles.link}>Attach file</Text></Pressable><Pressable accessibilityRole="button" disabled={busy} onPress={()=>void run(sync)}><Text style={styles.link}>Retry saved work</Text></Pressable></View>
        <VoiceMessage key={owner} disabled={busy||!!active} onTranscript={setText} onError={setError}/>
      </>:null}
      {screen==='recordings'?<><Text style={styles.muted}>Thirty-second audio segments are saved privately on this device. Upload resumes with the same recording and segment IDs. Interruptions remain visible.</Text><View style={styles.row}>{courses.map(item=><Pressable accessibilityRole="button" key={item.id} onPress={()=>setCourse(item.id)}><Text style={styles.link}>{course===item.id?'✓ ':''}{item.name}</Text></Pressable>)}</View>{!active?<Button title="Start lecture" disabled={busy||!course} onPress={()=>void run(async()=>{const record=await startRecording(owner!,course!,'Lecture · '+new Date().toLocaleString());setActive(record);await saveLocal(record)})}/>:<View style={styles.card}><Text style={styles.heading}>Recording saved segments · {Math.round(active.durationMs/1000)}s</Text><Button title="Pause / resume" disabled={busy} onPress={()=>void run(async()=>{setActive(await updateRecording(active,active.paused?'resume':'pause'))})}/><Button title="Stop and save" disabled={busy} onPress={()=>void run(async()=>{const stopped=await updateRecording(active,'stop');await saveLocal(stopped);setActive(null)})}/><Pressable accessibilityRole="button" onPress={()=>void run(async()=>setActive(await updateRecording(active,'inspect')))}><Text style={styles.link}>Check saved duration</Text></Pressable></View>}
        {records.map(record=><View key={record.id} style={styles.card}><Text style={styles.heading}>{record.title}</Text><Text style={styles.muted}>{record.segments.length} saved segments · {record.finalized?'Uploaded':record.stopped?'Saved on device':'Capture unfinished'}{record.interrupted?' · interruption/gap recorded':''}</Text><Pressable accessibilityRole="button" disabled={busy||!!active} onPress={()=>void run(async()=>{const updated=await updateRecording(record,'inspect');await saveLocal(updated);if(!updated.stopped)setActive(updated)})}><Text style={styles.link}>Recover native segments</Text></Pressable><Button title="Upload / retry" disabled={busy||!record.stopped||record.finalized} onPress={()=>void run(()=>uploadRecording(record))}/>{record.finalized?<LectureDetails id={record.id} run={action=>void run(action)}/>:null}</View>)}
        {remoteRecords.filter(item=>!records.some(record=>record.id===item.id)).map(item=><View key={item.id} style={styles.card}><Text style={styles.heading}>{item.title}</Text><LectureDetails id={item.id} run={action=>void run(action)}/></View>)}
      </>:null}
      {screen==='inbox'?<><Responsibilities key={owner} sessionId={session?.id} courseId={session?.courseId} run={action=>void run(action)}/><Button title={pushEnabled?'Push enabled':'Enable optional phone notifications'} disabled={busy||pushEnabled} onPress={()=>void run(async()=>setPushEnabled(await enablePush()))}/>{notices.map(notice=><View key={notice.id} style={styles.card}><Text style={styles.heading}>{notice.title}</Text><Text style={styles.muted}>{notice.status}</Text><Pressable accessibilityRole="button" onPress={()=>void run(async()=>{const link=safeDeepLink(notice.url);if(link)await openConversation(await api.json<Conversation>(`/v1/sessions/${link.session}`))})}><Text style={styles.link}>Open result</Text></Pressable><Pressable accessibilityRole="button" onPress={()=>void run(()=>api.json(`/v1/notifications/${notice.id}/ack`,{method:'POST'}))}><Text style={styles.link}>Mark read</Text></Pressable></View>)}</>:null}
      {error?<Text accessibilityRole="alert" style={styles.error}>{error}</Text>:null}
    </ScrollView>
  </KeyboardAvoidingView>;
}
