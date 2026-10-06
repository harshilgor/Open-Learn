'use client';
import {useCallback,useEffect,useState} from 'react';
import {request} from '@/lib/api';
import {Button} from './ui/button';
type Routine={id:string;revision:number;active:boolean;message:string;timezone:string;schedule:{type:string;cron?:string;rrule?:string}};
export function RoutineControls(){
 const [items,setItems]=useState<Routine[]>([]),[busy,setBusy]=useState(''),[error,setError]=useState('');
 const load=useCallback(async()=>{const result=await request<{routines:Routine[]}>('/v1/reminders');setItems(result.routines);},[]);
 useEffect(()=>{let live=true;void request<{routines:Routine[]}>('/v1/reminders').then(result=>{if(live)setItems(result.routines);}).catch(e=>{if(live)setError(e.message);});return()=>{live=false;};},[]);
 async function control(item:Routine,action:'pause'|'resume'|'delete'){setBusy(item.id);try{await request('/v1/reminder-routines/'+item.id,{method:'PATCH',body:JSON.stringify({expectedRevision:item.revision,action})});await load();setError('');}catch(e){setError(e instanceof Error?e.message:'Could not update routine.');}finally{setBusy('');}}
 if(!items.length&&!error)return null;
 return <section aria-label="Scheduled routines"><h3>Routines</h3>{items.map(item=><article key={item.id} className="buddy-preview"><strong>{item.message}</strong><p>{item.active?'Active':'Paused'} · {item.timezone}</p><Button variant="outline" disabled={busy===item.id} onClick={()=>void control(item,item.active?'pause':'resume')}>{item.active?'Pause':'Resume'}</Button></article>)}{error?<p role="alert">{error}</p>:null}</section>;
}
