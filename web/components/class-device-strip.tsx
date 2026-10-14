"use client";
import {useEffect,useState} from 'react';
import {classDevices,type CaptureStatus} from '@/lib/class-devices';
import {Button} from './ui/button';
export function ClassDeviceStrip({classId,onAudioEnd}:{classId:string;onAudioEnd?:(value:number)=>void}){
  const [status,setStatus]=useState<CaptureStatus|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  useEffect(()=>{
    const controller=new AbortController();let pending=false;
    const refresh=async()=>{if(pending||document.visibilityState==='hidden')return;pending=true;try{const value=await classDevices.status(classId,controller.signal);if(!controller.signal.aborted){setStatus(value);onAudioEnd?.(value.run?.audioEndMs||0);setError('');}}catch(cause){if(!controller.signal.aborted)setError(String(cause));}finally{pending=false;}};
    void refresh();const timer=setInterval(()=>void refresh(),3000);
    return()=>{controller.abort();clearInterval(timer);};
  },[classId,onAudioEnd]);
  async function send(action:'pause'|'resume'|'stop'|'handoff'){
    if(!status?.run)return;setBusy(true);
    try{await classDevices.command(classId,status.run,action);setStatus(await classDevices.status(classId));setError('');}catch(cause){setError(String(cause));}finally{setBusy(false);}
  }
  if(!status?.run)return error?<p role="status">Recording device status is unavailable.</p>:null;
  const run=status.run;
  const pendingStop=status.commands.some(command=>command.runId===run.id&&['stop','handoff'].includes(command.action)&&['pending','delivered'].includes(command.state));
  return <aside aria-label="Phone recording status" className="class-device-strip">
    <p role="status"><strong>{pendingStop?'Stop requested':run.state==='recording'?'Recording from phone':run.state==='paired'?'Phone paired; start on phone':`Phone ${run.state}`}</strong> · {run.stale?'Connection stale':'Connected'}{run.backlog?` · ${run.backlog} audio slices waiting to upload`:''}{run.batteryPercent!==null?` · Battery ${run.batteryPercent}%`:''}</p>
    {run.stale?<p>The phone may still be recording. A Stop request is confirmed only when the phone acknowledges it.</p>:null}
    {!['stopped','interrupted','paired'].includes(run.state)?<div>
      <Button size="sm" variant="outline" disabled={busy||pendingStop} onClick={()=>void send(run.state==='paused'?'resume':'pause')}>{run.state==='paused'?'Request resume on phone':'Pause phone microphone'}</Button>
      <Button size="sm" variant="outline" disabled={busy||pendingStop} onClick={()=>void send('handoff')}>Stop phone for device switch</Button>
      <Button size="sm" disabled={busy||pendingStop} onClick={()=>void send('stop')}>Stop class</Button>
    </div>:null}
    {error?<p role="alert">{error}</p>:null}
  </aside>;
}
