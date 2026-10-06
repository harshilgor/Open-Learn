'use client';
import {useState} from 'react';
import {request} from '@/lib/api';
export function ReminderDeliveryStatus({id}:{id:string}){
 const [rows,setRows]=useState<{channel:string;status:string}[]|null>(null),[error,setError]=useState('');
 return <details onToggle={event=>{if(event.currentTarget.open)void request<{deliveries:{channel:string;status:string}[]}>('/v1/reminders/'+encodeURIComponent(id)).then(result=>{setRows(result.deliveries);setError('');}).catch(e=>setError(e.message));}}><summary>Delivery status</summary>{rows?.length?rows.map(row=><p key={row.channel}>{row.channel}: {row.status.replaceAll('_',' ')}</p>):<p>{rows?'No deliveries yet.':'Loading…'}</p>}{error?<p role="alert">{error}</p>:null}</details>;
}
