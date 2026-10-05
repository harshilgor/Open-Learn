'use client';
import {useEffect,useRef,useState} from 'react';
import {request} from '@/lib/api';
import {ACCOUNT_CHANGED} from '@/lib/account-session';
import type {AgentTask} from '@/lib/assistant-client';

type Connection={id:string;email:string;status:string;capabilities:string[]};
type Action={id:string;revision:number;status:string;actionHash:string;expiresAt:number;account:string;kind:string;mail?:{to:string[];cc:string[];subject:string;body:string};event?:{calendarId:string;summary:string;description:string;start:string;end:string;timeZone:string;attendees:string[];sendUpdates:string};baseEvent?:Record<string,unknown>;attachments:{id:string;name:string;size:number}[];operation?:{status:string;reasonCode?:string;providerId?:string}|null};
type Children={items:{id:string;childId:string;status:string;assignment:string;verification?:{status:string;semanticSupport?:string}}[];budget?:{children_remaining:number;calls_remaining:number;tokens_remaining:number}|null};

function ActionReview({action,onChanged}:{action:Action;onChanged:()=>void}) {
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  const keys=useRef<Record<string,string>>({});
  async function decide(decision:'approve'|'reject') {
    setBusy(true);setError('');const identity=`${action.id}:${action.actionHash}:${decision}`;
    keys.current[identity] ||= crypto.randomUUID();
    try {await request(`/v1/assistant/approvals/${encodeURIComponent(action.id)}/decision`,{method:'POST',headers:{'Idempotency-Key':keys.current[identity]},body:JSON.stringify({decision,expectedRevision:action.revision,actionHash:action.actionHash})});onChanged();}
    catch(cause){setError(cause instanceof Error?cause.message:'Decision unavailable.');}finally{setBusy(false);}
  }
  async function reconcile(){setBusy(true);setError('');try{await request(`/v1/assistant/approvals/${encodeURIComponent(action.id)}/reconcile`,{method:'POST'});onChanged();}catch(cause){setError(cause instanceof Error?cause.message:'Recovery unavailable.');}finally{setBusy(false);}}
  return <article aria-label="Connected action review">
    <h4>{action.kind.replaceAll('_',' ')} · {action.status.replaceAll('_',' ')}</h4>
    <p>Account: {action.account}. Review expires {new Date(action.expiresAt*1000).toLocaleString()}.</p>
    {action.mail?<><p>To: {action.mail.to.join(', ')}; Cc: {action.mail.cc.join(', ')||'none'}</p><p>Subject: {action.mail.subject}</p><pre style={{whiteSpace:'pre-wrap'}}>{action.mail.body}</pre></>:null}
    {action.event?<><p>Calendar: {action.event.calendarId}</p><p>{action.event.summary}: {action.event.start} → {action.event.end} ({action.event.timeZone})</p><p>{action.event.description}</p><p>Attendees: {action.event.attendees.join(', ')||'none'}; notifications: {action.event.sendUpdates}</p>{action.baseEvent?<details><summary>Original event before this change</summary><pre>{JSON.stringify(action.baseEvent,null,2)}</pre></details>:null}</>:null}
    <p>Attachments: {action.attachments.map(item=>`${item.name} (${item.size} bytes)`).join(', ')||'none'}</p>
    {action.status==='draft'?<><button disabled={busy} onClick={()=>void decide('approve')}>Approve this exact action</button><button disabled={busy} onClick={()=>void decide('reject')}>Reject action</button></>:null}
    {action.operation?<p role="status">Provider operation: {action.operation.status.replaceAll('_',' ')}{action.operation.reasonCode?` · ${action.operation.reasonCode.replaceAll('_',' ')}`:''}{action.operation.providerId?` · receipt ${action.operation.providerId}`:''}</p>:null}
    {action.operation?.status==='outcome_unknown'?<><p>The provider may already have applied this action. It will not be automatically sent again.</p><button disabled={busy} onClick={()=>void reconcile()}>Check provider outcome</button></>:null}
    {error?<p role="alert">{error} Retry preserves the decision identity.</p>:null}
  </article>;
}

export function ConnectedTaskPanel({task}:{task:AgentTask}) {
  const [open,setOpen]=useState(false),[connections,setConnections]=useState<Connection[]>([]),[actions,setActions]=useState<Action[]>([]),[children,setChildren]=useState<Children>({items:[]});
  const [enabled,setEnabled]=useState(false),[delegation,setDelegation]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const [account,setAccount]=useState(''),[kind,setKind]=useState('gmail_send'),[recipient,setRecipient]=useState(''),[subject,setSubject]=useState(''),[body,setBody]=useState(''),[calendar,setCalendar]=useState('primary'),[eventId,setEventId]=useState(''),[start,setStart]=useState(''),[end,setEnd]=useState(''),[zone,setZone]=useState('America/Los_Angeles'),[assignment,setAssignment]=useState('');
  const [scopes,setScopes]=useState<string[]>([]),[sourceKind,setSourceKind]=useState('drive'),[sourceResult,setSourceResult]=useState(''),[fileId,setFileId]=useState('');
  const [attachmentIds,setAttachmentIds]=useState<string[]>([]);
  const epoch=useRef(0),pending=useRef<{signature:string;key:string}|null>(null);
  const refreshRef=useRef<()=>Promise<void>>(async()=>{});
  useEffect(()=>{
    if(!open)return;
    const version=++epoch.current;let inflight=false;
    async function update(){if(inflight)return;inflight=true;try{
      const [apps,writes,bounded]=await Promise.all([request<{items:Connection[];enabled:boolean;delegationEnabled:boolean}>('/v1/assistant/app-connections'),request<{items:Action[]}>(`/v1/assistant/tasks/${encodeURIComponent(task.id)}/actions`),request<Children>(`/v1/assistant/tasks/${encodeURIComponent(task.id)}/children`)]);
      if(epoch.current!==version)return;setConnections(apps.items);setEnabled(apps.enabled);setDelegation(apps.delegationEnabled);setActions(writes.items);setChildren(bounded);
    }catch(cause){if(epoch.current===version)setError(cause instanceof Error?cause.message:'Connected task status unavailable.');}finally{inflight=false;}}
    refreshRef.current=update;void update();const timer=window.setInterval(()=>void update(),5000);
    const invalidate=()=>{epoch.current++;};
    function reset(){epoch.current++;setConnections([]);setActions([]);setChildren({items:[]});setSourceResult('');setAccount('');setSubject('');setBody('');setRecipient('');setAssignment('');setFileId('');setAttachmentIds([]);setCalendar('primary');setEventId('');setStart('');setEnd('');setZone('America/Los_Angeles');setScopes([]);setError('');setBusy(false);pending.current=null;setOpen(false);}
    window.addEventListener(ACCOUNT_CHANGED,reset);
    return()=>{invalidate();window.clearInterval(timer);window.removeEventListener(ACCOUNT_CHANGED,reset);};
  },[open,task.id]);
  async function mutate(path:string,value:unknown){
    const version=epoch.current;setBusy(true);setError('');const signature=JSON.stringify({path,value});
    if(pending.current?.signature!==signature)pending.current={signature,key:crypto.randomUUID()};
    try{await request(path,{method:'POST',headers:{'Idempotency-Key':pending.current.key},body:JSON.stringify(value)});if(epoch.current===version){pending.current=null;await refreshRef.current();}}
    catch(cause){if(epoch.current===version)setError(cause instanceof Error?cause.message:'Request failed.');}finally{if(epoch.current===version)setBusy(false);}
  }
  async function connect(){const version=epoch.current;setBusy(true);setError('');try{const result=await request<{authorizationUrl:string}>('/v1/assistant/app-connections/google/authorize',{method:'POST',body:JSON.stringify({capabilities:scopes})});if(epoch.current!==version)return;const url=new URL(result.authorizationUrl);if(url.origin!=='https://accounts.google.com')throw new Error('Invalid sign-in destination.');window.open(url.href,'_blank','noopener,noreferrer');}catch(cause){if(epoch.current===version)setError(cause instanceof Error?cause.message:'Connection setup unavailable.');}finally{if(epoch.current===version)setBusy(false);}}
  async function read(){setBusy(true);setError('');const version=epoch.current;try{const result=await request(`/v1/assistant/app-connections/${encodeURIComponent(account)}/sources?kind=${sourceKind}`);if(epoch.current===version)setSourceResult(JSON.stringify(result,null,2));}catch(cause){if(epoch.current===version)setError(cause instanceof Error?cause.message:'Source unavailable.');}finally{if(epoch.current===version)setBusy(false);}}
  async function disconnect(id:string){const version=epoch.current;setBusy(true);try{await request(`/v1/assistant/app-connections/${encodeURIComponent(id)}`,{method:'DELETE'});if(epoch.current===version)await refreshRef.current();}catch(cause){if(epoch.current===version)setError(cause instanceof Error?cause.message:'Disconnect failed.');}finally{if(epoch.current===version)setBusy(false);}}
  return <details open={open} onToggle={event=>setOpen(event.currentTarget.open)}><summary>Connected actions and child tasks</summary>
    {open?<>
      <p>Each email or calendar change needs review. Unattended write grants are disabled. Child tasks cannot send external actions or create further children.</p>
      {!enabled?<p>New connector actions are disabled. Existing reviews and receipts remain visible.</p>:null}
      <fieldset disabled={busy||!enabled}><legend>Google connection permissions</legend>{['drive_read','gmail_read','gmail_send','calendar_write'].map(scope=><label key={scope}><input type="checkbox" checked={scopes.includes(scope)} onChange={event=>setScopes(previous=>event.target.checked?[...previous,scope]:previous.filter(item=>item!==scope))}/>{scope.replaceAll('_',' ')}</label>)}<button type="button" disabled={!scopes.length} onClick={()=>void connect()}>Connect selected Google permissions</button></fieldset>
      {connections.map(connection=><p key={connection.id}>{connection.email} · {connection.status} · {connection.capabilities.join(', ')} <button type="button" disabled={busy||connection.status!=='connected'} onClick={()=>void disconnect(connection.id)}>Disconnect {connection.email}</button></p>)}
      <label>Connected account <select value={account} onChange={event=>setAccount(event.target.value)}><option value="">Select account</option>{connections.filter(item=>item.status==='connected').map(item=><option key={item.id} value={item.id}>{item.email}</option>)}</select></label>
      <details><summary>Read connected sources</summary><p>Provider text is untrusted evidence. Each request reads a bounded page.</p><select aria-label="Source provider" value={sourceKind} onChange={event=>setSourceKind(event.target.value)}><option value="drive">Drive</option><option value="gmail">Gmail</option></select><button disabled={busy||!account} onClick={()=>void read()}>Read source page</button><pre style={{whiteSpace:'pre-wrap'}}>{sourceResult}</pre><label>Drive file ID <input value={fileId} onChange={event=>setFileId(event.target.value)}/></label><button disabled={busy||!account||!fileId} onClick={()=>void mutate(`/v1/assistant/app-connections/${encodeURIComponent(account)}/drive/${encodeURIComponent(fileId)}/import`,{})}>Import file as material</button></details>
      <form onSubmit={event=>{event.preventDefault();const value={connectionId:account,expectedTaskRevision:task.revision,kind,...(kind==='gmail_send'?{mail:{to:recipient.split(',').map(item=>item.trim()).filter(Boolean),subject,body,attachmentIds}}:{event:{calendarId:calendar,...(kind==='calendar_update'?{eventId}:{}),summary:subject,description:body,start,end,timeZone:zone,attendees:[],sendUpdates:'none'}})};void mutate(`/v1/assistant/tasks/${encodeURIComponent(task.id)}/actions`,value);}}>
        <fieldset disabled={busy||!enabled||!account}><legend>Prepare an action for review</legend><label>Action <select value={kind} onChange={event=>setKind(event.target.value)}><option value="gmail_send">Send email</option><option value="calendar_create">Create calendar event</option><option value="calendar_update">Update calendar event</option></select></label>
        {kind==='gmail_send'?<label>Recipients, separated by commas <input required value={recipient} onChange={event=>setRecipient(event.target.value)}/></label>:<><label>Calendar ID <input required value={calendar} onChange={event=>setCalendar(event.target.value)}/></label>{kind==='calendar_update'?<label>Event ID <input required value={eventId} onChange={event=>setEventId(event.target.value)}/></label>:null}<label>Start with UTC offset <input required placeholder="2026-10-05T10:00:00-07:00" value={start} onChange={event=>setStart(event.target.value)}/></label><label>End with UTC offset <input required value={end} onChange={event=>setEnd(event.target.value)}/></label><label>IANA timezone <input required value={zone} onChange={event=>setZone(event.target.value)}/></label></>}
        <label>Subject or title <input required maxLength={200} value={subject} onChange={event=>setSubject(event.target.value)}/></label><label>Body or description <textarea required maxLength={10000} value={body} onChange={event=>setBody(event.target.value)}/></label><button>Prepare review; do not send yet</button></fieldset>
        {kind==='gmail_send'?<fieldset disabled={busy}><legend>Attach verified task files (up to three)</legend>{task.artifacts.map(artifact=><label key={artifact.id}><input type="checkbox" checked={attachmentIds.includes(artifact.id)} disabled={!attachmentIds.includes(artifact.id)&&attachmentIds.length>=3} onChange={event=>setAttachmentIds(previous=>event.target.checked?[...previous,artifact.id]:previous.filter(id=>id!==artifact.id))}/>{artifact.name}</label>)}</fieldset>:null}
      </form>
      {actions.map(action=><ActionReview key={action.id} action={action} onChanged={()=>void refreshRef.current()}/>)}
      <form onSubmit={event=>{event.preventDefault();void mutate(`/v1/assistant/tasks/${encodeURIComponent(task.id)}/children`,{expectedRevision:task.revision,kind:task.kind==='research'?'research':'lab_analysis',assignment});}}><fieldset disabled={busy||!delegation||!['research','lab_analysis','sandbox_lab'].includes(task.kind)}><legend>Bounded child task</legend><label>Assignment <input required maxLength={400} value={assignment} onChange={event=>setAssignment(event.target.value)}/></label><button>Start child with inherited scope</button></fieldset></form>
      {children.budget?<p>Remaining shared limits: {children.budget.children_remaining} children, {children.budget.calls_remaining} read calls, {children.budget.tokens_remaining} reserved token units.</p>:null}
      {children.items.map(child=><p key={child.id}>{child.assignment} · {child.status.replaceAll('_',' ')}{child.verification?.semanticSupport?` · ${child.verification.semanticSupport.replaceAll('_',' ')}`:''}</p>)}
      {error?<p role="alert">{error} Failed submissions retain their retry identity.</p>:null}
    </>:null}
  </details>;
}
