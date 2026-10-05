import {useEffect,useState,useRef} from 'react';
import {View,Text,TextInput,Pressable,Switch} from 'react-native';
import * as Crypto from 'expo-crypto';
import {api} from './account';
import {styles} from './theme';
import type {ResponsibilitySpec} from './generated/api';
type Item={id:string;revision:number;status:string;spec:ResponsibilitySpec};
export function Responsibilities({sessionId,courseId,run}:{sessionId?:string;courseId?:string|null;run:(action:()=>Promise<unknown>)=>void}){
  const [items,setItems]=useState<Item[]>([]),[editing,setEditing]=useState<Item|null>(null),[goal,setGoal]=useState('Prepare a short course review'),[zone,setZone]=useState('America/Los_Angeles'),[day,setDay]=useState('0'),[hour,setHour]=useState('9'),[push,setPush]=useState(false),[dates,setDates]=useState<number[]>([]);
  const key=useRef(Crypto.randomUUID()),preview=useRef('');
  async function refresh(){const result=await api.json<{responsibilities:Item[]}>('/v1/assistant/responsibilities');setItems(result.responsibilities)}
  useEffect(()=>{void refresh().catch(()=>undefined)},[]);
  function spec():ResponsibilitySpec{return {...editing?.spec,sessionId:editing?.spec.sessionId||sessionId!,courseId:editing?.spec.courseId||courseId!,goal,timezone:zone,weekday:Number(day),hour:Number(hour),minute:0,schedule:'weekly',expoPush:push,lectureEvents:true,maxRunsPerWeek:3,quietStart:22,quietEnd:8};}
  return <View style={styles.card}><Text style={styles.heading}>Ongoing course work</Text><Text style={styles.muted}>Weekly review and finalized-lecture preparation. Quiet hours: 22:00–08:00. Editing stops obsolete active work.</Text>
    {items.map(item=><View key={item.id}><Text style={styles.text}>{item.spec.goal} · {item.status}</Text><View style={styles.row}>{(['pause','disable','resume','stop_all'] as const).map(action=><Pressable accessibilityRole="button" key={action} onPress={()=>run(async()=>{await api.json(`/v1/assistant/responsibilities/${item.id}/commands`,{method:'POST',body:JSON.stringify({action,expectedRevision:item.revision})});await refresh()})}><Text style={styles.link}>{action==='stop_all'?'Stop all':action}</Text></Pressable>)}<Pressable accessibilityRole="button" onPress={()=>{setEditing(item);setGoal(item.spec.goal);setZone(item.spec.timezone||'America/Los_Angeles');setDay(String(item.spec.weekday||0));setHour(String(item.spec.hour||9));setPush(!!item.spec.expoPush);setDates([])}}><Text style={styles.link}>Edit schedule and notifications</Text></Pressable></View></View>)}
    {(editing || sessionId && courseId)?<>
      <TextInput accessibilityLabel="Ongoing responsibility" style={styles.input} value={goal} onChangeText={value=>{setGoal(value);setDates([])}}/>
      <TextInput accessibilityLabel="IANA timezone" style={styles.input} value={zone} onChangeText={value=>{setZone(value);setDates([])}}/>
      <Text style={styles.muted}>Day: Monday 0 through Sunday 6; hour: 0–23</Text><TextInput accessibilityLabel="Weekly day" style={styles.input} keyboardType="number-pad" value={day} onChangeText={value=>{setDay(value);setDates([])}}/><TextInput accessibilityLabel="Weekly hour" style={styles.input} keyboardType="number-pad" value={hour} onChangeText={value=>{setHour(value);setDates([])}}/>
      <View style={styles.row}><Text style={styles.text}>Optional phone push</Text><Switch accessibilityLabel="Push for ongoing work" value={push} onValueChange={value=>{setPush(value);setDates([])}}/></View>
      <Pressable accessibilityRole="button" onPress={()=>run(async()=>{const value=spec();const result=await api.json<{nextOccurrences:number[]}>('/v1/assistant/responsibilities/preview',{method:'POST',body:JSON.stringify(value)});preview.current=JSON.stringify(value);setDates(result.nextOccurrences)})}><Text style={styles.link}>Preview next three runs</Text></Pressable>
      {dates.map(date=><Text key={date} style={styles.text}>{new Date(date*1000).toLocaleString(undefined,{timeZone:zone})}</Text>)}
      <Pressable accessibilityRole="button" disabled={!dates.length} onPress={()=>run(async()=>{const value=spec();if(JSON.stringify(value)!==preview.current)throw Error('Preview the updated schedule first.');await api.json(editing?`/v1/assistant/responsibilities/${editing.id}/commands`:'/v1/assistant/responsibilities',{method:'POST',headers:{'Idempotency-Key':key.current},body:JSON.stringify(editing?{action:'edit',expectedRevision:editing.revision,spec:value}:value)});key.current=Crypto.randomUUID();setEditing(null);setDates([]);await refresh()})}><Text style={styles.link}>Save ongoing work</Text></Pressable>
    </>:<Text style={styles.muted}>Choose a course conversation to create ongoing work.</Text>}
  </View>;
}
