import {useState} from 'react';
import {Text,View,Pressable} from 'react-native';
import {File,Directory,Paths} from 'expo-file-system';
import {useAudioPlayer} from 'expo-audio';
import * as Crypto from 'expo-crypto';
import {api,authenticated,account} from './account';
import {styles} from './theme';
type Detail={recordingStatus:string;captureInterrupted:boolean;error?:string;chunks:{missing:number[];failed:number;transcribed:number;serverConfirmed:number}};
export function LectureDetails({id,run}:{id:string;run:(action:()=>Promise<unknown>)=>void}){
  const [status,setStatus]=useState<Detail|null>(null),[blocks,setBlocks]=useState<{id:string;content:string;evidence:{startMs:number;endMs:number}[]}[]>([]),[transcript,setTranscript]=useState<{id:string;normalizedText:string;startMs:number;endMs:number}[]>([]),[chunks,setChunks]=useState<{sequenceNumber:number;startMs:number;endMs:number}[]>([]);
  const player=useAudioPlayer(null);
  const base=`/v1/learners/${account()?.owner}/lecture-recordings/${id}`;
  return <View><Pressable accessibilityRole="button" onPress={()=>run(async()=>{const [state,notes,text,audio]=await Promise.all([api.json<Detail>(base),api.json<{blocks:typeof blocks}>(base+'/notes'),api.json<{segments:typeof transcript}>(base+'/transcript'),api.json<{chunks:typeof chunks}>(base+'/chunks')]);setStatus(state);setBlocks(notes.blocks);setTranscript(text.segments);setChunks(audio.chunks)})}><Text style={styles.link}>Inspect processing, transcript, notes and audio</Text></Pressable>
    {status?<Text style={styles.muted}>{status.recordingStatus} · {status.chunks.transcribed}/{status.chunks.serverConfirmed} transcribed{status.captureInterrupted?' · capture has an interruption':''}{status.chunks.missing.length?' · missing segments: '+status.chunks.missing.join(', '):''}{status.error?' · '+status.error:''}</Text>:null}
    {status?.chunks.failed?<Pressable accessibilityRole="button" onPress={()=>run(()=>api.json(base+'/retry',{method:'POST'}))}><Text style={styles.link}>Retry failed processing</Text></Pressable>:null}
    {chunks.map(chunk=><Pressable accessibilityRole="button" key={chunk.sequenceNumber} onPress={()=>run(async()=>{const owner=account()?.owner;if(!owner)throw Error('Sign in first.');const response=await authenticated(base+`/chunks/${chunk.sequenceNumber}/audio`);const scope=await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256,owner);const folder=new Directory(Paths.document,'audio-review',scope);folder.create({intermediates:true,idempotent:true});const extension=response.headers.get('content-type')?.includes('webm')?'webm':response.headers.get('content-type')?.includes('mp4')?'m4a':'wav';const file=new File(folder,`${id}_${chunk.sequenceNumber}.${extension}`);const bytes=new Uint8Array(await response.arrayBuffer());if(account()?.owner!==owner)throw Error('Account changed; playback cancelled.');file.write(bytes);player.replace(file.uri);player.play()})}><Text style={styles.link}>Play audio {Math.round(chunk.startMs/1000)}–{Math.round(chunk.endMs/1000)}s</Text></Pressable>)}
    {chunks.length?<Pressable accessibilityRole="button" onPress={()=>player.pause()}><Text style={styles.link}>Pause playback</Text></Pressable>:null}
    {transcript.map(segment=><Text key={segment.id} style={styles.text}>{Math.round(segment.startMs/1000)}s · {segment.normalizedText}</Text>)}
    {blocks.map(block=><View key={block.id}><Text style={styles.text}>{block.content}</Text><Text style={styles.muted}>{block.evidence.map(source=>`${Math.round(source.startMs/1000)}–${Math.round(source.endMs/1000)}s`).join(', ')}</Text></View>)}
  </View>;
}
