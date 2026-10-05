import {useEffect,useState} from 'react';
import {Text,View,Pressable} from 'react-native';
import {useAudioRecorder,useAudioRecorderState,useAudioPlayer,RecordingPresets,AudioModule,setAudioModeAsync} from 'expo-audio';
import {File} from 'expo-file-system';
import * as Crypto from 'expo-crypto';
import {authenticated,account} from './account';
import {journals} from './storage';
import {styles} from './theme';
export function VoiceMessage({onTranscript,onError,disabled}:{onTranscript:(text:string)=>void;onError:(text:string)=>void;disabled:boolean}){
  const recorder=useAudioRecorder({...RecordingPresets.HIGH_QUALITY,directory:'document'});
  const state=useAudioRecorderState(recorder,250);
  const player=useAudioPlayer(null);
  const [clip,setClip]=useState<{uri:string;duration:number;key:string}|null>(null),[busy,setBusy]=useState(false);
  const owner=account()?.owner;
  useEffect(()=>{
    if(!owner || !state.durationMillis || state.isRecording || clip || !recorder.uri)return;
    const saved={uri:recorder.uri,duration:state.durationMillis,key:Crypto.randomUUID()};
    setClip(saved);void journals.write('voice:'+owner,saved).catch(error=>onError(error.message));
  },[state.isRecording,state.durationMillis,clip,recorder,owner,onError]);
  async function act(action:()=>Promise<unknown>){setBusy(true);try{await action()}catch(error){onError(error instanceof Error?error.message:'Voice capture failed.')}finally{setBusy(false)}}
  return <View style={styles.card}><Text style={styles.heading}>Voice message</Text><Text style={styles.muted}>Review your voice and correct its transcript before sending. Lectures use the separate recording screen.</Text>
    {!clip?<Pressable accessibilityRole="button" disabled={busy||disabled} onPress={()=>void act(async()=>{if(state.isRecording){const duration=state.durationMillis;await recorder.stop();if(recorder.uri){const saved={uri:recorder.uri,duration,key:Crypto.randomUUID()};setClip(saved);await journals.write('voice:'+account()?.owner,saved)}}else{const permission=await AudioModule.requestRecordingPermissionsAsync();if(!permission.granted)throw Error('Microphone permission denied.');await setAudioModeAsync({allowsRecording:true,playsInSilentMode:true});await recorder.prepareToRecordAsync();recorder.record({forDuration:90});}})}><Text style={styles.link}>{state.isRecording?`Stop voice · ${Math.round(state.durationMillis/1000)}s`:'Record short voice'}</Text></Pressable>:<View style={styles.row}>
      <Pressable accessibilityRole="button" onPress={()=>{player.replace(clip.uri);player.play()}}><Text style={styles.link}>Play voice</Text></Pressable>
      <Pressable accessibilityRole="button" disabled={busy||disabled} onPress={()=>void act(async()=>{const bytes=await new File(clip.uri).bytes();const response=await authenticated('/v1/mobile/voice-transcriptions',{method:'POST',headers:{'Idempotency-Key':clip.key,'Content-Type':'audio/mp4','X-Audio-Duration-Ms':String(Math.max(1,clip.duration))},body:bytes as unknown as BodyInit});if(account()?.owner!==owner)throw Error('Account changed; transcription cancelled.');const result=await response.json() as {text:string};onTranscript(result.text)})}><Text style={styles.link}>Transcribe for review</Text></Pressable>
      <Pressable accessibilityRole="button" onPress={()=>void act(async()=>{player.pause();new File(clip.uri).delete();setClip(null);await journals.write('voice:'+account()?.owner,null)})}><Text style={styles.link}>Delete voice</Text></Pressable>
    </View>}
    <Pressable accessibilityRole="button" disabled={busy||disabled||state.isRecording} onPress={()=>void act(async()=>{const saved=await journals.read<{uri:string;duration:number;key:string}>('voice:'+account()?.owner);if(saved)setClip(saved)})}><Text style={styles.link}>Recover saved voice</Text></Pressable>
  </View>;
}
