import type {Recording} from './protocol';

export function batteryPercent(value:unknown):number|null{
  return typeof value==='number'&&Number.isFinite(value)&&value>=0&&value<=100?Math.round(value):null;
}
export function createBatteryReader(read:()=>Promise<unknown>,now=Date.now,timeoutMs=1500){
  let value:number|null=null,checkedAt=-Infinity,pending:Promise<number|null>|null=null;
  return async()=>{
    if(now()-checkedAt<30000)return value;
    if(pending)return pending;
    pending=(async()=>{
      let timer:ReturnType<typeof setTimeout>|undefined;
      try{value=batteryPercent(await Promise.race([read(),new Promise<null>(resolve=>{timer=setTimeout(()=>resolve(null),timeoutMs);})]));}catch{value=null;}finally{if(timer)clearTimeout(timer);checkedAt=now();pending=null;}
      return value;
    })();
    return pending;
  };
}
export function captureHeartbeat(record:Recording,battery:number|null){
  const setup=record.classSetup;
  return {state:record.stopped?(record.interrupted?'interrupted':'stopped'):record.paused?'paused':'recording',audioEndMs:(setup?.startMs||0)+record.durationMs,sealedChunkCount:record.segments.length,backlog:record.segments.filter(segment=>!segment.acknowledged).length,batteryPercent:batteryPercent(battery),endClass:record.stopped&&Boolean(setup?.finalizeOnStop)};
}
