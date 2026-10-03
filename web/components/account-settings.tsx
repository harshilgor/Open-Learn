'use client';
import { useEffect, useRef, useState } from 'react';
import { SourceMemorySettings } from './source-memory-settings';
import { request } from '@/lib/api';
import { authenticatedFetch } from '@/lib/account-session';
import { pendingCommands, forgetCommand, PENDING_CHANGED, type PendingCommand } from '@/lib/offline-commands';
import { readSettingsPreferences, saveSettingsPreferences, type SettingsPreferences } from '@/lib/settings-preferences';
import { enqueueCheckpoint, flushDevice, syncState } from '@/lib/device-sync';
import { ACCOUNT_CHANGED, accountManager, signIn, signOut, useDeviceGrant } from '@/lib/account-session';

type Account = { ownerId: string; displayName: string; mode: string; deviceId?: string; localImportAvailable?: boolean };
type Device = { id: string; name: string; kind: string; revoked_at?: number; expires_at: number };

export function AccountSettings() {
  const [account, setAccount] = useState<Account>();
  const [devices, setDevices] = useState<Device[]>([]);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState('My desktop');
  const [kind, setKind] = useState<'desktop' | 'canvas'>('desktop');
  const [grant, setGrant] = useState('');
  const [newGrant, setNewGrant] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [preferences, setPreferences] = useState<Partial<SettingsPreferences>>({});
  const [inventory, setInventory] = useState<{ checksum: string; tables: Record<string, number>; message: string }>();
  const [pending, setPending] = useState(0);
  const [commands, setCommands] = useState<PendingCommand[]>([]);
  const [revision, setRevision] = useState(0);
  const [portable,setPortable]=useState<Record<string,unknown>>();
  const [packageReview,setPackageReview]=useState<{checksum:string;sourceProfile:string;tables:Record<string,number>;message:string}>();
  const generation=useRef(0);
  async function reload() {
    const version=++generation.current;
    const current = await request<Account>('/v1/account');
    if(version!==generation.current)return;
    setAccount(current); setCommands(pendingCommands(current.ownerId));
    const linked=current.mode==='web'?(await request<{ devices: Device[] }>('/v1/account/devices')).devices:[];
    const prefs = await request<{ revision: number; preferences: object }>('/v1/account/preferences');
    if(version!==generation.current)return;
    setDevices(linked);
    setRevision(prefs.revision); setPreferences(prefs.preferences);
    if (current.deviceId) setPending(syncState(current.ownerId, current.deviceId).pending.length);
  }
  async function run(action: () => Promise<void>) {
    setBusy(true); setMessage('');
    try { await action(); } catch (error) { setMessage(error instanceof Error ? error.message : 'The account operation failed.'); }
    finally { setBusy(false); }
  }
  useEffect(() => {
    const refresh = () => { void reload().catch(error => setMessage(String(error.message))); };
    const changed=()=>{generation.current++;setAccount(undefined);setDevices([]);setCommands([]);setPreferences({});setGrant('');setConfirmation('');setSelectedPackage();refresh();};
    function setSelectedPackage(){setPortable(undefined);setPackageReview(undefined);setInventory(undefined);setPending(0);setNewGrant('');}
    refresh(); window.addEventListener(ACCOUNT_CHANGED, changed); window.addEventListener(PENDING_CHANGED, refresh);
    return () => { generation.current++;window.removeEventListener(ACCOUNT_CHANGED, changed); window.removeEventListener(PENDING_CHANGED, refresh); };
  }, []);
  return <section style={{ display: 'grid', gap: 20, maxWidth: 720 }} aria-label="Account and devices">
    <header><h2>Account &amp; devices</h2><p>{account?.displayName || 'Account'} · {account?.mode === 'local' ? 'Local profile — not synchronized' : account?.mode || 'Loading…'}</p></header>
    {message && <p role="status">{message}</p>}
    {account?.mode === 'local' ? <><p>Your local history stays on this installation until you explicitly import it.</p><button disabled={busy || !accountManager()} onClick={() => void run(signIn)}>Sign in</button>{!accountManager() && <p>An account provider must be configured before sign-in is available.</p>}</> : <button disabled={busy} onClick={() => void run(signOut)}>Sign out on this browser</button>}
    <fieldset disabled={busy}><legend>Link this device</legend><label>Device grant<input type="password" value={grant} onChange={e => setGrant(e.target.value)} autoComplete="off" /></label><button onClick={() => void run(async () => { await useDeviceGrant(grant); setGrant(''); await reload(); })}>Use grant</button><p>Obtain a grant from Account &amp; devices in your signed-in browser. Grants expire after 30 days.</p></fieldset>
    {account?.mode === 'web' && <>
      <fieldset disabled={busy}><legend>Create a device grant</legend><label>Device name<input value={name} onChange={e => setName(e.target.value)} maxLength={120} /></label><label>Device type<select value={kind} onChange={e => setKind(e.target.value as 'desktop' | 'canvas')}><option value="desktop">Desktop</option><option value="canvas">Canvas reader</option></select></label><button onClick={() => void run(async () => { const result = await request<{ token: string }>('/v1/account/devices', { method: 'POST', body: JSON.stringify({ name, kind }) }); setNewGrant(result.token); await reload(); })}>Create grant</button>{newGrant && <label>Copy this secret once<input readOnly type="password" value={newGrant} /><button onClick={() => void navigator.clipboard.writeText(newGrant)}>Copy grant</button></label>}<p>Canvas grants are reserved for the Canvas reader and cannot access your notes or account controls.</p></fieldset>
      <section><h3>Linked devices</h3>{devices.length === 0 && <p>No linked devices.</p>}{devices.map(device => <div key={device.id} style={{ display: 'flex', gap: 12, alignItems: 'center' }}><span>{device.name} · {device.kind} · {device.revoked_at ? 'Revoked' : device.expires_at * 1000 < Date.now() ? 'Expired' : 'Active'}</span><button disabled={busy || Boolean(device.revoked_at)} onClick={() => void run(async () => { await request(`/v1/account/devices/${device.id}`, { method: 'DELETE' }); await reload(); })}>Revoke</button></div>)}</section>
      <section><h3>Data &amp; privacy</h3><button disabled={busy} onClick={() => void run(async () => { const data = await request('/v1/account/export'); const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })); const link = document.createElement('a'); link.href = url; link.download = 'openlearn-account.json'; link.click(); URL.revokeObjectURL(url); })}>Export account</button><label>Type DELETE to delete this account<input value={confirmation} onChange={e => setConfirmation(e.target.value)} /></label><button disabled={busy || confirmation !== 'DELETE'} onClick={() => void run(async () => { await request('/v1/account', { method: 'DELETE', body: JSON.stringify({ confirmation: 'DELETE' }) }); await signOut(); setMessage('Account access revoked and deletion requested.'); })}>Delete account</button></section>
    </>}
    {account?.mode === 'web' && account.localImportAvailable && <section><h3>Import local history</h3><p>Copy this installation’s local profile into your account. Existing local history is retained.</p><button disabled={busy} onClick={() => void run(async () => setInventory(await request('/v1/account/local-profile')))}>Review local inventory</button>{inventory && <><ul>{Object.entries(inventory.tables).map(([table, count]) => <li key={table}>{table.replaceAll('_', ' ')}: {count}</li>)}</ul><p>{inventory.message}</p><button disabled={busy} onClick={() => void run(async () => { await request('/v1/account/local-profile/import', { method: 'POST', body: JSON.stringify({ checksum: inventory.checksum, confirm_copy: true }) }); setMessage('Local history copied into this account. The original profile is intact.'); })}>Confirm copy into account</button><button disabled={busy} onClick={() => void run(async () => { await request('/v1/account/local-profile/import', { method: 'DELETE' }); setInventory(undefined); setMessage('Interrupted import reset. Local source history is intact.'); })}>Reset interrupted import</button></>}</section>}
    {commands.length > 0 && <section><h3>Changes awaiting confirmation</h3><p>These changes are stored on this device. They are not confirmed server evidence.</p>{commands.map(command => <article key={command.id}><p>{command.url.includes('/workspace-notes/') ? 'Note edit' : 'Quiz action'} · {command.status === 'conflict' ? 'Needs review: the server revision changed' : 'Pending'}</p><details><summary>Review your saved change</summary><pre style={{ whiteSpace: 'pre-wrap' }}>{String(JSON.parse(command.body).body || JSON.parse(command.body).answer || JSON.parse(command.body).response || 'Your original action and revision are preserved for retry.')}</pre></details><button disabled={busy} onClick={() => void run(async () => { const result = await authenticatedFetch(command.url, { method: command.method, body: command.body, headers: { 'Content-Type': 'application/json', ...(command.commandKey ? { 'Idempotency-Key': command.commandKey } : {}) } }); if (!result.ok) throw new Error(result.status === 409 ? 'This change conflicts with the current server revision. Your local change is preserved; open the note or quiz to review it.' : 'The change is still pending. Sign in or reconnect and retry.'); await reload(); })}>Retry saved change</button><button disabled={busy} onClick={() => { forgetCommand(command.ownerId, command.id); setCommands(pendingCommands(command.ownerId)); }}>Discard pending copy</button></article>)}</section>}
    <section><h3>Synchronization</h3><p>Preferences revision {revision}. {pending} device checkpoints pending acknowledgment.</p><button disabled={busy} onClick={() => void run(reload)}>Refresh from server</button><button disabled={busy} onClick={() => void run(async () => { saveSettingsPreferences(preferences); setMessage('Account preferences applied on this device.'); })}>Apply account preferences here</button><button disabled={busy} onClick={() => void run(async () => { await request('/v1/account/preferences', { method: 'PUT', body: JSON.stringify({ expected_revision: revision, preferences: readSettingsPreferences() }) }); await reload(); })}>Save this device’s preferences to account</button>{account?.deviceId && <><button disabled={busy} onClick={() => void run(async () => { setPending(enqueueCheckpoint(account.ownerId, account.deviceId!, { action: 'manual_sync' })); setPending(await flushDevice(account.ownerId, account.deviceId!)); setMessage('Device checkpoint acknowledged.'); })}>Synchronize device checkpoint</button><button disabled={busy || !pending} onClick={() => void run(async () => setPending(await flushDevice(account.ownerId, account.deviceId!)))}>Retry pending checkpoints</button></>}</section>
    {account?.mode==='local'&&<button disabled={busy} onClick={()=>void run(async()=>{const data=await request('/v1/account/export');const url=URL.createObjectURL(new Blob([JSON.stringify(data)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download='openlearn-local-profile.json';link.click();URL.revokeObjectURL(url);})}>Export local history for another device</button>}
    {account?.mode==='web'&&<section><h3>Import a portable history package</h3><p>Review an export from another device, then explicitly copy it into this empty account.</p><label>Account export file<input type="file" accept="application/json,.json" disabled={busy} onChange={event=>{const file=event.target.files?.[0];if(file)void run(async()=>{if(file.size>100_000_000)throw new Error('Export file exceeds 100 MB.');const data=JSON.parse(await file.text()) as Record<string,unknown>;const review=await request<{checksum:string;sourceProfile:string;tables:Record<string,number>;message:string}>('/v1/account/import-package/review',{method:'POST',body:JSON.stringify(data)});setPortable(data);setPackageReview(review);});}}/></label>{portable&&packageReview&&<><p>{packageReview.message}</p><ul>{Object.entries(packageReview.tables).map(([table,count])=><li key={table}>{table.replaceAll('_',' ')}: {count}</li>)}</ul><button disabled={busy} onClick={()=>void run(async()=>{await request('/v1/account/import-package',{method:'POST',body:JSON.stringify({package:portable,checksum:packageReview.checksum,confirm_copy:true})});setPortable(undefined);setPackageReview(undefined);setMessage('History copied. Original device history remains intact.');})}>Confirm portable copy</button></>}</section>}
    {account&&<SourceMemorySettings key={account.ownerId}/>}
  </section>;
}
