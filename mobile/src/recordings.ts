import {Directory,File,Paths} from 'expo-file-system';
import * as Crypto from 'expo-crypto';
import {AudioModule} from 'expo-audio';
import Capture,{type CaptureState} from './modules-placeholder';
import {journals} from './storage';
import {api,account} from './account';
import {syncRecording,type Recording} from './protocol';
const key=(owner:string)=>'recordings:'+owner;
export async function recordings(owner:string){return await journals.read<Recording[]>(key(owner)) || [];}
export async function saveRecording(value:Recording){const list=await recordings(value.owner);const position=list.findIndex(r=>r.id===value.id);if(position<0)list.push(value);else list[position]=value;await journals.write(key(value.owner),list);}
export function mergeCapture(record:Recording,state:CaptureState){
  if(record.id!==state.recordingId)throw Error('Capture identity mismatch.');
  return {...record,segments:state.segments.map(segment=>({...record.segments.find(s=>s.sequence===segment.sequence),...segment})),durationMs:state.durationMs,interrupted:state.interrupted,paused:state.status==='paused',stopped:['stopped','interrupted'].includes(state.status)};
}
export async function startRecording(owner:string,courseId:string,title:string){
  const permission=await AudioModule.requestRecordingPermissionsAsync();if(!permission.granted)throw Error('Microphone permission is required to record.');
  if(account()?.owner!==owner)throw Error('Account changed; recording cancelled.');
  const id='rec_'+Crypto.randomUUID().replaceAll('-','');
  const scope=await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256,owner);
  const directory=new Directory(Paths.document,'lectures',scope,id);directory.create({intermediates:true});
  const record:Recording={id,owner,courseId,title,startedAtMs:Date.now(),directory:directory.uri,segments:[],durationMs:0,interrupted:false,stopped:false,created:false,finalized:false};
  await saveRecording(record);
  const state=await Capture.start(directory.uri,id);if(account()?.owner!==owner){await Capture.stop();throw Error('Account changed; recording stopped.');}const merged=mergeCapture(record,state);merged.startedAtMs=state.startedAtMs;await saveRecording(merged);return merged;
}
export async function updateRecording(record:Recording,action:'stop'|'pause'|'resume'|'inspect'){
  const state=action==='inspect'?await Capture.inspect(record.directory):await Capture[action]();
  const updated=mergeCapture(record,state);await saveRecording(updated);return updated;
}
export async function uploadRecording(record:Recording){
  const owner=account()?.owner;if(!owner)throw Error('Sign in first.');
  await syncRecording(record,owner,api,saveRecording,uri=>new File(uri).bytes(),async bytes=>Array.from(new Uint8Array(await Crypto.digest(Crypto.CryptoDigestAlgorithm.SHA256,bytes as BufferSource))).map(v=>v.toString(16).padStart(2,'0')).join(''));
}
