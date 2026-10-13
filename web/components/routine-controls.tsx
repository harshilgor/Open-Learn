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
 return <section className="ol-section" aria-label="Scheduled routines"><h2>Routines<small>{items.length}</small></h2><div className="ol-card ol-list">{items.map(item=><article key={item.id} className="ol-row"><div className="ol-row-main"><strong>{item.message}</strong><span className="ol-row-meta"><span className="ol-badge" data-tone={item.active?'brand':undefined}>{item.active?'Active':'Paused'}</span><span>{item.timezone}</span></span></div><div className="ol-row-actions"><Button size="sm" variant="outline" disabled={busy===item.id} onClick={()=>void control(item,item.active?'pause':'resume')}>{item.active?'Pause':'Resume'}</Button></div></article>)}</div>{error?<p role="alert" className="ol-row-meta">{error}</p>:null}</section>;
}
