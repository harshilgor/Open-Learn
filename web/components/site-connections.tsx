'use client';
import {useCallback,useEffect,useState} from 'react';
import {Button} from './ui/button';
import {apiBaseUrl,request} from '@/lib/api';
import {authenticatedFetch,ACCOUNT_CHANGED} from '@/lib/account-session';
import {SITE_CHANGED,type SiteConnection} from '@/lib/browser-assistant';
import styles from './browser-assistant.module.css';

export function SiteConnections({compact=false}:{compact?:boolean}) {
  const [login,setLogin]=useState<{id:string;revision:number;url:string}|null>(null);
  const [sites,setSites]=useState<SiteConnection[]>([]),[origin,setOrigin]=useState(''),[label,setLabel]=useState('My university portal'),[platform,setPlatform]=useState<'canvas'|'generic'>('canvas'),[executor,setExecutor]=useState<'local'|'public_fetch'|'cloud'>('local'),[approved,setApproved]=useState(''),[rememberSignIn,setRememberSignIn]=useState(false),[config,setConfig]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const [capabilities,setCapabilities]=useState<{enabled:boolean;providerConfigured:boolean;cloud:Record<string,boolean>}|null>(null);
  const refresh=useCallback(async()=>{const result=await request<{connections:SiteConnection[]}>('/v1/site-connections');setSites(result.connections);},[]);
  const refreshCapabilities=useCallback(async()=>{try{const result=await request<{enabled:boolean;providerConfigured:boolean;cloud:Record<string,boolean>}>('/v1/assistant/capabilities');setCapabilities(result);}catch{setCapabilities(null);}},[]);
  useEffect(()=>{let live=true;void request<{connections:SiteConnection[]}>('/v1/site-connections').then(result=>{if(live)setSites(result.connections);}).catch(e=>{if(live)setError(e.message);});void request<{enabled:boolean;providerConfigured:boolean;cloud:Record<string,boolean>}>('/v1/assistant/capabilities').then(result=>{if(live)setCapabilities(result);}).catch(()=>{if(live)setCapabilities(null);});const change=()=>{setConfig('');setLogin(null);void refresh().catch(e=>setError(e.message));void refreshCapabilities();};window.addEventListener(ACCOUNT_CHANGED,change);return()=>{live=false;window.removeEventListener(ACCOUNT_CHANGED,change);};},[refresh,refreshCapabilities]);
  const cloudReady=!!capabilities?.enabled&&!!capabilities.providerConfigured&&['enabled','paidRoutesEnabled','tariffConfigured','credentialsConfigured','runtimeInstalled','egressVerified','lifecycleVerified'].every(key=>capabilities.cloud[key]===true);
  const privateLoginReady=cloudReady&&capabilities?.cloud.privateLoginVerified===true;
  async function pair(site:SiteConnection) {
    setBusy(true);setError('');
    try {
      const value=await request<Record<string,unknown>>(`/v1/site-connections/${site.id}/pair`,{method:'POST'});
      const desktop=(window as Window & {formaDesktop?:{apiToken?:string}}).formaDesktop;
      setConfig(JSON.stringify({...value,backend:apiBaseUrl(),desktopToken:desktop?.apiToken},null,2));
      await refresh();window.dispatchEvent(new Event(SITE_CHANGED));
    } catch(e){setError(e instanceof Error?e.message:'Pairing failed.');}finally{setBusy(false);}
  }
  async function signIn(site:SiteConnection) {
    setBusy(true);setError('');
    try {const result=await request<{connection:SiteConnection;liveViewUrl:string}>(`/v1/site-connections/${site.id}/cloud-login`,{method:'POST',body:JSON.stringify({expectedRevision:site.revision})});setLogin({id:site.id,revision:result.connection.revision,url:result.liveViewUrl});await refresh();}
    catch(e){setError(e instanceof Error?e.message:'Sign-in unavailable.');}finally{setBusy(false);}
  }
  async function finishLogin() {
    if(!login)return;setBusy(true);
    try{await request(`/v1/site-connections/${login.id}/cloud-login/finish`,{method:'POST',body:JSON.stringify({expectedRevision:login.revision})});setLogin(null);await refresh();}
    catch(e){setLogin(null);await refresh().catch(()=>undefined);setError(e instanceof Error?e.message:'Could not finish sign-in.');}finally{setBusy(false);}
  }
  async function updateRememberSignIn(site:SiteConnection,enabled:boolean) {
    setBusy(true);setError('');
    try {await request(`/v1/site-connections/${site.id}`,{method:'PATCH',body:JSON.stringify({expectedRevision:site.revision,cloudLogin:enabled})});await refresh();window.dispatchEvent(new Event(SITE_CHANGED));}
    catch(e){setError(e instanceof Error?e.message:'Could not update saved sign-in settings.');}
    finally{setBusy(false);}
  }
  async function connect() {
    setBusy(true);setError('');
    try {
      const site=await request<SiteConnection>('/v1/site-connections',{method:'POST',body:JSON.stringify({label,origin,platform,executor,
        category:platform==='canvas'?'university_lms':'study',preferred:true,aliases:platform==='canvas'?['my university portal','Canvas']:[],
        cloudLogin:executor==='cloud'&&rememberSignIn&&privateLoginReady,timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,approvedOrigins:approved.split(',').map(s=>s.trim()).filter(Boolean)})});
      await refresh();window.dispatchEvent(new Event(SITE_CHANGED));
      if(executor==='local')await pair(site);
    }catch(e){setError(e instanceof Error?e.message:'Connection failed.');}finally{setBusy(false);}
  }
  async function download() {
    try {
      const desktop=(window as Window & {formaDesktop?:{apiToken?:string}}).formaDesktop;
      const headers:Record<string,string>={};if(desktop?.apiToken)headers['X-Forma-Desktop-Token']=desktop.apiToken;
      const response=await authenticatedFetch(apiBaseUrl()+'/v1/browser-companion/download',{headers});
      if(!response.ok)throw Error('The browser companion download is unavailable.');
      const url=URL.createObjectURL(await response.blob()),a=document.createElement('a');a.href=url;a.download='openlearn-browser-companion.zip';a.click();URL.revokeObjectURL(url);
    }catch(e){setError(e instanceof Error?e.message:'Download failed.');}
  }
  return <section className={compact?'':styles.panel} aria-label="Connected websites">
    <h3>Connected websites</h3><p className={styles.muted}>Connect your university portal or another study website. Local browser reads use your existing sign-in and run while the browser and OpenLearn are available.</p>
    <ul className={styles.list}>{sites.map(site=><li className={styles.fact} key={site.id}>
      <strong>{site.label}</strong>
      <p className={styles.muted}>{site.origin} · {site.status.replaceAll('_',' ')}{site.lastSuccessfulSync?` · checked ${new Date(site.lastSuccessfulSync*1000).toLocaleString()}`:''}</p>
      {site.executor==='cloud'?privateLoginReady?<><label><input type="checkbox" checked={!!site.cloudLogin} disabled={busy} onChange={event=>void updateRememberSignIn(site,event.target.checked)}/> Remember sign-in for this website (removed after 30 days without use)</label>{site.cloudLogin?<Button size="sm" variant="outline" disabled={busy} onClick={()=>void signIn(site)}>{site.status==='logging_in'?'Reopen sign-in':'Sign in securely'}</Button>:null}</>:<p className={styles.muted}>{site.cloudLogin?'This saved sign-in is paused until private-browser checks pass. Disconnect and reconnect to use a temporary session.':'This connection uses temporary, read-only cloud browsing. Saved sign-in is not available yet.'}</p>:null}
      <div className={styles.actions}>
        <Button size="sm" variant="outline" disabled={busy} onClick={()=>void request(`/v1/site-connections/${site.id}/schedule`,{method:'POST',body:JSON.stringify({intervalHours:24,active:true})}).then(()=>setError('Daily refresh enabled. Local browser refresh requires your browser and OpenLearn to be available.')).catch(e=>setError(e.message))}>Refresh daily</Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={()=>void request(`/v1/site-connections/${site.id}/schedule`,{method:'POST',body:JSON.stringify({intervalHours:24,active:false})}).catch(e=>setError(e.message))}>Stop daily refresh</Button>
        {site.executor==='local'?<Button size="sm" variant="outline" disabled={busy} onClick={()=>void pair(site)}>Pair browser</Button>:null}
        <Button size="sm" variant="ghost" disabled={busy} onClick={()=>void request(`/v1/site-connections/${site.id}`,{method:'PATCH',body:JSON.stringify({expectedRevision:site.revision,preferred:true})}).then(refresh).then(()=>window.dispatchEvent(new Event(SITE_CHANGED))).catch(e=>setError(e.message))}>Use by default</Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={()=>void request(`/v1/site-connections/${site.id}`,{method:'DELETE'}).then(refresh).then(()=>window.dispatchEvent(new Event(SITE_CHANGED))).catch(e=>setError(e.message))}>{site.cloudLogin?'Disconnect and forget sign-in':'Disconnect'}</Button>
      </div>
      <details><summary>Approved additional websites</summary><form onSubmit={event=>{event.preventDefault();const value=String(new FormData(event.currentTarget).get('origins') || '');setBusy(true);void request<SiteConnection>(`/v1/site-connections/${site.id}`,{method:'PATCH',body:JSON.stringify({expectedRevision:site.revision,approvedOrigins:value.split(',').map(item=>item.trim()).filter(Boolean)})}).then(async updated=>{await refresh();if(updated.executor==='local')await pair(updated);}).catch(e=>setError(e.message)).finally(()=>setBusy(false));}}><label>Document or sign-in website addresses<input name="origins" defaultValue={(site.approvedOrigins || []).join(', ')} placeholder="https://documents.your-university.edu"/></label><Button size="sm" disabled={busy} type="submit">Save approved websites</Button></form></details>
    </li>)}</ul>
    <details><summary>Add a website</summary><div className={styles.form}>
      <label>Name<input value={label} onChange={e=>setLabel(e.target.value)}/></label>
      <label>Website address<input value={origin} placeholder="https://canvas.your-university.edu" onChange={e=>setOrigin(e.target.value)}/></label>
      <label>Platform<select value={platform} onChange={e=>setPlatform(e.target.value as 'canvas'|'generic')}><option value="canvas">Canvas</option><option value="generic">Other website</option></select></label>
      <label>Connection<select value={executor} onChange={e=>setExecutor(e.target.value as typeof executor)}><option value="local">My signed-in browser</option><option value="public_fetch">Public pages</option><option value="cloud" disabled={!cloudReady}>Temporary read-only cloud browser{cloudReady?'':' (not available yet)'}</option></select></label>
      {executor==='cloud'?privateLoginReady?<label><input type="checkbox" checked={rememberSignIn} onChange={event=>setRememberSignIn(event.target.checked)}/> Remember sign-in for this website. Open Learn deletes the saved browser profile after 30 days without use.</label>:<p className={styles.muted}>Cloud sessions are temporary and read-only. You can connect public sites; saved account sign-in will be enabled after its privacy checks pass.</p>:null}
      <label>Additional approved document websites, separated by commas<input value={approved} onChange={e=>setApproved(e.target.value)} placeholder="https://documents.your-university.edu"/></label>
      <Button disabled={busy||!origin||!label||(executor==='cloud'&&!cloudReady)} onClick={()=>void connect()}>Connect website</Button>
    </div></details>
    {executor==='local' || config?<details open={!!config}><summary>Set up the browser companion</summary><p className={styles.muted}>Download and unzip the companion. In Chrome or Edge, open Extensions, enable Developer mode, choose Load unpacked, and select its folder. Open the companion and paste the pairing below. Approve access to your connected website.</p><Button variant="outline" onClick={()=>void download()}>Download companion</Button>{config?<div className={styles.form}><label>Pairing configuration · contains a private device credential<textarea className={styles.credential} readOnly value={config}/></label><Button variant="outline" onClick={()=>void navigator.clipboard.writeText(config).catch(()=>setError('Select and copy the pairing text manually.'))}>Copy pairing</Button></div>:null}</details>:null}
    {login?<div className={styles.panel}><p>Open the temporary browser, sign in to your university account, then finish here. This sign-in link expires after ten minutes.</p><a href={login.url} target="_blank" rel="noopener noreferrer">Open secure sign-in browser</a><Button disabled={busy} onClick={()=>void finishLogin()}>I have finished signing in</Button></div>:null}
    {error?<p className={styles.error} role="alert">{error}</p>:null}
  </section>;
}
