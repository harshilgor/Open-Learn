"use client";
import {useEffect,useState} from 'react';
import {request} from '@/lib/api';
import {Button} from './ui/button';
type Verification={id:string;state:string;revision:number;startMs:number;endMs:number;model:string;error?:string};
export function ClassVerificationStatus({classId,version}:{classId:string;version:number}){
  const [items,setItems]=useState<Verification[]>([]),[receipt,setReceipt]=useState<Record<string,string>>({}),[error,setError]=useState(''),[busy,setBusy]=useState('');
  const base=`/v1/class-sessions/${encodeURIComponent(classId)}/verification-requests`;
  useEffect(()=>{let active=true;void request<{items:Verification[]}>(base).then(data=>{if(active)setItems(data.items);}).catch(()=>undefined);return()=>{active=false;};},[base,version]);
  async function update(item:Verification,attach=false){setBusy(item.id);try{const data=await request<{items:Verification[]}>(`${base}/${encodeURIComponent(item.id)}/${attach?'receipt':`retry?revision=${item.revision}`}`,{method:'POST',...(attach?{body:JSON.stringify({expectedRevision:item.revision,externalRequestId:receipt[item.id]})}:{})});setItems(data.items);setError('');}catch(cause){setError(String(cause));}finally{setBusy('');}}
  const pending=items.filter(item=>!['complete','deleted'].includes(item.state));
  if(!pending.length)return null;
  return <details><summary>Recorded audio verification ({pending.length})</summary>{pending.map(item=><div key={item.id}><p>{Math.floor(item.startMs/1000)}–{Math.floor(item.endMs/1000)}s · {item.state.replaceAll('_',' ')}</p>{item.error?<p>{item.error}</p>:null}{['submission_unknown','submitting'].includes(item.state)?<><p>A provider submission may already be billed. Attach its receipt to resume verification without submitting again.</p><label>AssemblyAI transcript request ID<input value={receipt[item.id]||''} maxLength={160} onChange={event=>setReceipt(current=>({...current,[item.id]:event.target.value}))}/></label><Button size="sm" disabled={busy===item.id||!receipt[item.id]} onClick={()=>void update(item,true)}>Match provider receipt</Button></>:item.state==='failed'?<Button size="sm" disabled={busy===item.id} onClick={()=>void update(item)}>Retry verification</Button>:null}</div>)}{error?<p role="alert">{error}</p>:null}</details>;
}
