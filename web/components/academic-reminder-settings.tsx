'use client';
import {useEffect,useState} from 'react';
import {Button} from './ui/button';
import {request} from '@/lib/api';
import styles from './browser-assistant.module.css';

type Policy={id:string;revision:number;active:boolean;offsetsMinutes:number[];channels:string[];timezone:string;dateOnlyTime?:string;quietStart:number;quietEnd:number;catchupMinutes:number};
type Notification={id:string;title:string;status:string;source?:{locator:string}};
export function AcademicReminderSettings() {
  const [policies,setPolicies]=useState<Policy[]>([]),[inbox,setInbox]=useState<Notification[]>([]),[time,setTime]=useState('09:00'),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const refresh=async()=>{const [p,n]=await Promise.all([request<{policies:Policy[]}>('/v1/reminder-policies'),request<{notifications:Notification[]}>('/v1/notifications')]);setPolicies(p.policies);setInbox(n.notifications);};
  useEffect(()=>{let live=true;void Promise.all([request<{policies:Policy[]}>('/v1/reminder-policies'),request<{notifications:Notification[]}>('/v1/notifications')]).then(([p,n])=>{if(live){setPolicies(p.policies);setInbox(n.notifications);}}).catch(e=>{if(live)setError(e.message);});return()=>{live=false;};},[]);
  const enable=async()=>{setBusy(true);try{await request('/v1/reminder-policies',{method:'POST',body:JSON.stringify({offsetsMinutes:[1440],channels:['inbox','desktop'],timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,dateOnlyTime:time})});await refresh();}catch(e){setError(e instanceof Error?e.message:'Could not enable reminders.');}finally{setBusy(false);}};
  const push=async()=>{setBusy(true);try{
    const c=await request<{vapidPublicKey?:string}>('/v1/assistant/capabilities');
    if(!c.vapidPublicKey)throw Error('Hosted push notifications have not been configured. Inbox and desktop reminders are available.');
    if(!('serviceWorker' in navigator) || !('PushManager' in window))throw Error('This browser does not support push notifications.');
    if(await Notification.requestPermission()!=='granted')throw Error('Notification permission was declined.');
    const registration=await navigator.serviceWorker.register('/openlearn-reminders.js',{scope:'/openlearn-notifications/'});
    await new Promise<void>((resolve,reject)=>{const worker=registration.installing || registration.waiting;if(registration.active)return resolve();if(!worker)return reject(Error('Notification worker unavailable.'));worker.addEventListener('statechange',()=>{if(worker.state==='activated')resolve();if(worker.state==='redundant')reject(Error('Notification worker failed.'));});});
    const padded=c.vapidPublicKey.replace(/-/g,'+').replace(/_/g,'/'),key=Uint8Array.from(atob(padded),char=>char.charCodeAt(0));
    const subscription=await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:key});
    const serialized=subscription.toJSON();
    await request('/v1/notification-subscriptions',{method:'POST',body:JSON.stringify({endpoint:serialized.endpoint,keys:serialized.keys})});
    for(const policy of policies.filter(p=>p.active))await request(`/v1/reminder-policies/${policy.id}`,{method:'PATCH',body:JSON.stringify({...policy,id:undefined,revision:undefined,expectedRevision:policy.revision,channels:['inbox','desktop','push']})});
    await refresh();
  }catch(e){setError(e instanceof Error?e.message:'Could not enable push.');}finally{setBusy(false);}};
  return <section className={styles.panel} aria-label="Academic reminders"><h3>Academic reminders</h3><p className={styles.muted}>Remind me one day before saved deadlines and exams. Inbox reminders stay available in OpenLearn; desktop alerts require the app to be running. Hosted push can notify you while the app is closed when configured.</p><div className={styles.form}><label>Reminder time for dates without a start time<input type="time" value={time} onChange={e=>setTime(e.target.value)}/></label></div><div className={styles.actions}><Button disabled={busy} onClick={()=>void enable()}>Enable academic reminders</Button><Button variant="outline" disabled={busy||!policies.some(p=>p.active)} onClick={()=>void push()}>Enable browser notifications</Button></div><ul className={styles.list}>{policies.map(policy=><li className={styles.fact} key={policy.id}>{policy.active?'Enabled':'Disabled'} · {policy.timezone}<Button variant="ghost" size="sm" onClick={()=>void request(`/v1/reminder-policies/${policy.id}`,{method:'PATCH',body:JSON.stringify({...policy,id:undefined,revision:undefined,expectedRevision:policy.revision,active:!policy.active})}).then(refresh).catch(e=>setError(e.message))}>{policy.active?'Disable':'Enable'}</Button></li>)}</ul><h3>Reminder inbox</h3>{inbox.length?<ul className={styles.list}>{inbox.map(n=><li className={styles.fact} key={n.id}>{n.title}{n.status==='available'?<Button variant="ghost" size="sm" onClick={()=>void request(`/v1/notifications/${n.id}/ack`,{method:'POST'}).then(refresh)}>Mark seen</Button>:null}</li>)}</ul>:<p className={styles.muted}>No reminders due yet.</p>}{error?<p className={styles.error} role="alert">{error}</p>:null}</section>;
}
