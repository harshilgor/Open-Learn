import {useEffect,useState} from 'react';
import {Text,TextInput,View,Pressable,Switch} from 'react-native';
import * as Crypto from 'expo-crypto';
import {api} from './account';
import type {AnswerCommand,backend__app__assessment_models__RevisionCommand as RevisionCommand} from './generated/api';
import {styles} from './theme';
type State={id:string;revision:number;status:string;current?:{id:string;stem:string;kind:string;options:{id:string;label:string}[];attemptId?:string|null};attempts?:{feedback?:string;score?:number|null}[];summary?:{score:number|null}};
export function Quiz({id,run}:{id:string;run:(action:()=>Promise<unknown>)=>void}){
  const [quiz,setQuiz]=useState<State|null>(null),[response,setResponse]=useState(''),[selected,setSelected]=useState<string[]>([]),[assisted,setAssisted]=useState(false),[error,setError]=useState('');
  async function refresh(){const result=await api.json<State>(`/v1/quizzes/${id}`);setQuiz(result);}
  useEffect(()=>{let live=true;const tick=()=>void api.json<State>(`/v1/quizzes/${id}`).then(result=>{if(live)setQuiz(result)}).catch(cause=>{if(live)setError(cause.message)});tick();const timer=setInterval(tick,5000);return()=>{live=false;clearInterval(timer)};},[id]);
  const current=quiz?.current;
  return <View style={styles.card}><Text style={styles.heading}>Practice quiz · {quiz?.status||'loading'}</Text>{current?<>
    <Text style={styles.text}>{current.stem}</Text>{current.options?.map(option=><Pressable accessibilityRole="button" key={option.id} onPress={()=>setSelected(previous=>current.kind==='multiple'?(previous.includes(option.id)?previous.filter(v=>v!==option.id):[...previous,option.id]):[option.id])}><Text style={styles.link}>{selected.includes(option.id)?'✓ ':''}{option.label}</Text></Pressable>)}
    {current.kind==='short'?<TextInput accessibilityLabel="Quiz answer" multiline style={styles.input} value={response} onChangeText={setResponse}/>:null}
    <View style={styles.row}><Text style={styles.text}>I used outside help</Text><Switch accessibilityLabel="Outside help used" value={assisted} onValueChange={setAssisted}/></View>
    {!current.attemptId?<View style={styles.row}>{(['answer','dont_know','skip'] as const).map(outcome=><Pressable accessibilityRole="button" key={outcome} onPress={()=>run(async()=>{const body:AnswerCommand={presentationId:current.id,expectedRevision:quiz!.revision,response,selectedIds:selected,externalHelp:assisted,outcome};await api.json(`/v1/quizzes/${id}/attempts`,{method:'POST',headers:{'Idempotency-Key':Crypto.randomUUID()},body:JSON.stringify(body)});await refresh()})}><Text style={styles.link}>{outcome==='answer'?'Submit answer':outcome==='dont_know'?'I don’t know':'Skip'}</Text></Pressable>)}</View>:null}
  </>:null}{quiz?.attempts?.slice(-1).map((attempt,index)=><Text key={index} style={styles.text}>{attempt.feedback||'Answer saved'}{attempt.score!=null?` · ${Math.round(attempt.score*100)}%`:''}</Text>)}
    <Pressable accessibilityRole="button" onPress={()=>run(async()=>{const body:RevisionCommand={expectedRevision:quiz!.revision};await api.json(`/v1/quizzes/${id}/next`,{method:'POST',headers:{'Idempotency-Key':Crypto.randomUUID()},body:JSON.stringify(body)});setSelected([]);setResponse('');setAssisted(false);await refresh()})}><Text style={styles.link}>Next question</Text></Pressable>{error?<Text style={styles.error}>{error}</Text>:null}
  </View>;
}
