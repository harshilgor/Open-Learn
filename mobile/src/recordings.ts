import {Directory,File,Paths} from 'expo-file-system';
import * as Crypto from 'expo-crypto';
import {AudioModule} from 'expo-audio';
import * as SecureStore from 'expo-secure-store';
import Capture,{type CaptureState} from './modules-placeholder';
import {journals} from './storage';
import {api,account} from './account';
import {syncRecording,ApiError,type Recording} from './protocol';
import {createBatteryReader,captureHeartbeat} from './capture-telemetry';
const readBattery=createBatteryReader(async()=>Capture.getBatteryPercent?await Capture.getBatteryPercent():null);
const key=(owner:string)=>'recordings:'+owner;
export async function recordings(owner:string){return await journals.read<Recording[]>(key(owner)) || [];}
export async function saveRecording(value:Recording){const safe={...value,...(value.classSetup?{classSetup:{...value.classSetup,captureCapability:undefined}}:{})};const list=await recordings(value.owner);const position=list.findIndex(r=>r.id===value.id&&r.classSetup?.runId===value.classSetup?.runId);if(position<0)list.push(safe);else list[position]=safe;await journals.write(key(value.owner),list);}
export function mergeCapture(record:Recording,state:CaptureState){
  if(record.id!==state.recordingId)throw Error('Capture identity mismatch.');
  return {...record,segments:state.segments.map(segment=>({...record.segments.find(s=>s.sequence===segment.sequence),...segment})),durationMs:state.durationMs,interrupted:state.interrupted,paused:state.status==='paused',stopped:['stopped','interrupted'].includes(state.status)};
}
export async function startRecording(owner:string,courseId:string,title:string,classCapture=false){
  for(const saved of await recordings(owner)){if(!saved.stopped){const recovered=await updateRecording(saved,'inspect');if(!recovered.stopped)throw Error('Stop the existing microphone capture before starting another class.');}}
  const permission=await AudioModule.requestRecordingPermissionsAsync();if(!permission.granted)throw Error('Microphone permission is required to record.');
  if(account()?.owner!==owner)throw Error('Account changed; recording cancelled.');
  const id='rec_'+Crypto.randomUUID().replaceAll('-','');
  const scope=await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256,owner);
  const directory=new Directory(Paths.document,'lectures',scope,id);directory.create({intermediates:true});
  const record:Recording={id,owner,courseId,title,startedAtMs:Date.now(),directory:directory.uri,segments:[],durationMs:0,interrupted:false,stopped:false,created:false,finalized:false};
  if(classCapture){let deviceId=await journals.read<string>('capture-device');if(!deviceId){deviceId=Crypto.randomUUID();await journals.write('capture-device',deviceId);}record.classSetup={deviceId,captureEpoch:1};record.markersMs=[];}
  await saveRecording(record);
  const state=await Capture.start(directory.uri,id);if(account()?.owner!==owner){await Capture.stop();throw Error('Account changed; recording stopped.');}const merged=mergeCapture(record,state);merged.startedAtMs=state.startedAtMs;await saveRecording(merged);return merged;
}
export async function updateRecording(record:Recording,action:'stop'|'pause'|'resume'|'inspect'){
  const state=action==='inspect'?await Capture.inspect(record.directory):await Capture[action]();
  const updated=mergeCapture(record,state);await saveRecording(updated);return updated;
}
export async function uploadRecording(record:Recording){
  const owner=account()?.owner;if(!owner)throw Error('Sign in first.');
  const capability=record.classSetup?.runId?await captureCredential(record):null;
  const authorized=capability?{...record,classSetup:{...record.classSetup!,captureCapability:capability}}:record;
  if(record.stopped&&record.classSetup?.runId)await reportCapture(record).catch(cause=>{if(!(cause instanceof ApiError&&cause.status===409))throw cause;});
  await syncRecording(authorized,owner,api,saveRecording,uri=>new File(uri).bytes(),async bytes=>Array.from(new Uint8Array(await Crypto.digest(Crypto.CryptoDigestAlgorithm.SHA256,bytes as BufferSource))).map(v=>v.toString(16).padStart(2,'0')).join(''));
  if(authorized!==record)Object.assign(record,{...authorized,classSetup:{...authorized.classSetup,captureCapability:undefined}});
}
export async function deleteLocalRecording(record:Recording){
  if(account()?.owner!==record.owner||!record.stopped||!record.finalized)throw Error('Stop and finish uploading before deleting local audio.');
  const scope=await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256,record.owner);
  const folder=new Directory(Paths.document,'lectures',scope,record.id);
  const target=record.classSetup?.runId?new Directory(folder,record.classSetup.runId):folder;
  if(target.uri!==record.directory)throw Error('Saved recording directory is invalid.');
  if(target.exists)target.delete();
  if(record.classSetup?.runId)await SecureStore.deleteItemAsync('class-capture-'+record.classSetup.runId);
  await journals.write(key(record.owner),(await recordings(record.owner)).filter(value=>value.id!==record.id||value.classSetup?.runId!==record.classSetup?.runId));
}

export type PhoneClaim={classId:string;recordingId:string;sessionId:string;title:string;courseId:string|null;runId:string;epoch:number;revision:number;sequenceBase:number;startMs:number;speechQuality?:'balanced'|'economical'};
export type PhonePairPreview={pairingId:string;classId:string;ownerId:string;title:string;expiresAt:number;requestingDeviceId:string;requestingDeviceName:string};
export async function previewPhoneClass(owner:string,code:string):Promise<PhonePairPreview>{
  if(account()?.owner!==owner)throw Error('Account changed; pairing cancelled.');
  let deviceId=await journals.read<string>('capture-device');if(!deviceId){deviceId=Crypto.randomUUID();await journals.write('capture-device',deviceId);}
  return api.json<PhonePairPreview>('/v1/class-pairings/preview',{method:'POST',body:JSON.stringify({code,deviceId})});
}
export async function finishPhonePairing(owner:string,code:string){
  await SecureStore.deleteItemAsync('class-pair-attempt-'+await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256,owner+':'+code));
}
export async function captureCredential(record:Recording){const secret=record.classSetup?.runId?await SecureStore.getItemAsync('class-capture-'+record.classSetup.runId):null;if(!secret)throw Error('This phone recording capability is unavailable. Saved audio remains on the device.');return secret;}
export async function claimPhoneClass(owner:string,code:string,consent:boolean):Promise<PhoneClaim>{
  if(!consent)throw Error('Confirm permission to record this class.');
  const permission=await AudioModule.requestRecordingPermissionsAsync();if(!permission.granted)throw Error('Microphone permission is required.');
  if(account()?.owner!==owner)throw Error('Account changed; pairing cancelled.');
  let deviceId=await journals.read<string>('capture-device');if(!deviceId){deviceId=Crypto.randomUUID();await journals.write('capture-device',deviceId);}
  const attemptKey='class-pair-attempt-'+await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256,owner+':'+code);
  const saved=await SecureStore.getItemAsync(attemptKey);const attempt=saved?JSON.parse(saved) as {commandId:string;captureCapability:string}:{commandId:Crypto.randomUUID(),captureCapability:Crypto.randomUUID().replaceAll('-','')+Crypto.randomUUID().replaceAll('-','')};
  await SecureStore.setItemAsync(attemptKey,JSON.stringify(attempt));
  const claim=await api.json<PhoneClaim>('/v1/class-pairings/claim',{method:'POST',body:JSON.stringify({code,deviceId,consent,...attempt})});
  // Preserve the idempotent claim if microphone startup needs a retry.
  await SecureStore.setItemAsync('class-capture-'+claim.runId,attempt.captureCapability);return claim;
}
export async function startPairedRecording(owner:string,claim:PhoneClaim){
  for(const saved of await recordings(owner)){if(!saved.stopped){const recovered=await updateRecording(saved,'inspect');if(!recovered.stopped)throw Error('Stop the existing phone microphone first.');}}
  if(account()?.owner!==owner)throw Error('Account changed; recording cancelled.');
  const scope=await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256,owner);
  const directory=new Directory(Paths.document,'lectures',scope,claim.recordingId,claim.runId);directory.create({intermediates:true});
  const deviceId=await journals.read<string>('capture-device');if(!deviceId)throw Error('This phone identity is unavailable.');
  const record:Recording={id:claim.recordingId,owner,courseId:claim.courseId||'',title:claim.title,startedAtMs:Date.now(),directory:directory.uri,segments:[],durationMs:0,interrupted:false,stopped:false,created:true,finalized:false,markersMs:[],classSetup:{deviceId,captureEpoch:claim.epoch,classId:claim.classId,runId:claim.runId,sequenceBase:claim.sequenceBase,startMs:claim.startMs,finalizeOnStop:false,speechQuality:claim.speechQuality}};
  // Revalidate ownership before opening the microphone after a delayed start.
  await api.json(`/v1/class-sessions/${claim.classId}/capture-runs/${claim.runId}/heartbeat`,{method:'POST',headers:{'X-Capture-Capability':await captureCredential(record)},body:JSON.stringify({state:'paired',audioEndMs:claim.startMs,sealedChunkCount:0})});
  await saveRecording(record);
  const state=await Capture.start(directory.uri,record.id);if(account()?.owner!==owner){await Capture.stop();throw Error('Account changed; microphone stopped.');}
  const merged=mergeCapture(record,state);await saveRecording(merged);await reportCapture(merged).catch(()=>undefined);return merged;
}
export async function reportCapture(record:Recording){
  const setup=record.classSetup;if(!setup?.runId)return {commands:[] as {id:string;action:'pause'|'resume'|'stop'|'handoff';expiresAt:number}[],batteryPercent:null};
  const batteryPercent=await readBattery();
  const status=await api.json<{commands:{id:string;action:'pause'|'resume'|'stop'|'handoff';expiresAt:number}[]}>(`/v1/class-sessions/${setup.classId}/capture-runs/${setup.runId}/heartbeat`,{method:'POST',headers:{'X-Capture-Capability':await captureCredential(record)},body:JSON.stringify(captureHeartbeat(record,batteryPercent))});
  return {...status,batteryPercent};
}
export async function acknowledgeCapture(record:Recording,commandId:string,accepted:boolean){
  const setup=record.classSetup;if(!setup?.runId)return;
  return api.json(`/v1/class-sessions/${setup.classId}/capture-commands/${commandId}/ack`,{method:'POST',headers:{'X-Capture-Capability':await captureCredential(record)},body:JSON.stringify({accepted,state:record.stopped?'stopped':record.paused?'paused':'recording',audioEndMs:(setup.startMs||0)+record.durationMs,sealedChunkCount:record.segments.length})});
}
