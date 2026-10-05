export type Segment={sequence:number;uri:string;startMs:number;endMs:number;sha256?:string;acknowledged?:boolean};
export type Recording={id:string;owner:string;title:string;courseId:string;startedAtMs:number;directory:string;segments:Segment[];durationMs:number;interrupted:boolean;paused?:boolean;stopped:boolean;created:boolean;finalized:boolean};
export type PendingMessage={key:string;owner:string;path?:string;body:Record<string,unknown>;state:'pending'|'conflict'};
export interface JsonStore {read<T>(key:string):Promise<T|null>;write(key:string,value:unknown):Promise<void>}
export interface Transport {json<T>(path:string,init?:RequestInit):Promise<T>;binary<T>(path:string,bytes:Uint8Array,headers:Record<string,string>):Promise<T>}
export class ApiError extends Error {constructor(public status:number,message:string){super(message)}}
export function safeDeepLink(value:string):{session:string;task?:string}|null {
  const match=/^(?:openlearn:\/\/|\/)?s\/([A-Za-z0-9_.:-]+)(?:\?task=([A-Za-z0-9_.:-]+))?$/.exec(value);
  return match?{session:match[1],task:match[2]}:null;
}
export async function syncRecording(record:Recording,currentOwner:string,api:Transport,save:(r:Recording)=>Promise<void>,read:(uri:string)=>Promise<Uint8Array>,hash:(bytes:Uint8Array)=>Promise<string>):Promise<void>{
  if(record.owner!==currentOwner)throw Error('This recording belongs to another account.');
  const base=`/v1/learners/${encodeURIComponent(currentOwner)}/lecture-recordings`;
  if(!record.created){await api.json(base,{method:'POST',body:JSON.stringify({id:record.id,title:record.title,courseId:record.courseId,startedAtMs:record.startedAtMs})});record.created=true;await save(record);}
  for(const segment of record.segments){
    if(segment.acknowledged)continue;
    const bytes=await read(segment.uri);
    if(bytes.length>4*1024*1024 || bytes.length<=44)throw Error('Invalid or oversized audio segment.');
    const checksum=await hash(bytes);
    if(segment.sha256 && segment.sha256!==checksum)throw Error('Saved audio changed; upload stopped.');
    segment.sha256=checksum;await save(record);
    await api.binary(`${base}/${record.id}/chunks/${segment.sequence}`,bytes,{'Content-Type':'audio/wav','X-Chunk-Start-Ms':String(segment.startMs),'X-Chunk-End-Ms':String(segment.endMs),'X-Chunk-Sha256':checksum});
    segment.acknowledged=true;await save(record);
  }
  if(record.stopped && !record.finalized && record.segments.length){
    const ordered=[...record.segments].sort((a,b)=>a.sequence-b.sequence);
    if(ordered.some((s,i)=>s.sequence!==i || !s.acknowledged))throw Error('Missing segment; cannot finalize this recording.');
    await api.json(`${base}/${record.id}/finalize`,{method:'POST',body:JSON.stringify({expectedChunkCount:ordered.length,durationMs:record.durationMs,captureInterrupted:record.interrupted,markersMs:[]})});
    record.finalized=true;await save(record);
  }
}
export async function flushMessages(owner:string,queue:PendingMessage[],api:Transport,save:()=>Promise<void>){
  for(const message of [...queue]){
    if(message.owner!==owner || message.state==='conflict')continue;
    try {const path=message.path||'/v1/assistant/messages';if(path!=='/v1/assistant/messages' && !/^\/v1\/sessions\/[A-Za-z0-9_.:-]+\/journey$/.test(path))throw Error('Unsupported saved message.');await api.json(path,{method:'POST',headers:{'Idempotency-Key':message.key},body:JSON.stringify(message.body)});queue.splice(queue.indexOf(message),1);await save();}
    catch(error){if(error instanceof ApiError && error.status===409){message.state='conflict';await save();continue;}throw error;}
  }
}
