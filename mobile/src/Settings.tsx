import { useEffect, useMemo, useRef, useState } from 'react';
import { AppState, Linking, Platform, Pressable, Text, View } from 'react-native';
import { account, api } from './account';
import { styles } from './theme';
import { APP_VERSION, verifiedStoreUrl } from './release';
import type { UsageActivityAdjustment, UsageActivityItem, UsageActivityResponse, UsageAllowance } from './protocol';
import { usedPercentageLabel, usageActivityLabel } from './usage-allowance';
import { parseUsageEventPage } from './usage-events';

type UsageSnapshot = { allowance: UsageAllowance; activity: UsageActivityItem[]; adjustments:UsageActivityAdjustment[]; receivedAt: number };
let eventCursor:{owner:string;revision:number}|null=null;
let eventPolling=false;

function monotonicNow() {
  return globalThis.performance?.now?.() ?? Date.now();
}

function isAllowance(value: unknown): value is UsageAllowance {
  if (!value || typeof value !== 'object') return false;
  const item = value as Partial<UsageAllowance>;
  const { grantedMicrocredits: grant, usedMicrocredits: used, heldMicrocredits: held, availableMicrocredits: available } = item;
  return Number.isFinite(item.serverTime) && Number.isSafeInteger(item.revision) && (item.revision ?? -1) >= 0 && Number.isSafeInteger(grant) &&
    Number.isSafeInteger(used) && Number.isSafeInteger(held) && Number.isSafeInteger(available) &&
    (grant ?? 0) > 0 && (used ?? -1) >= 0 && (held ?? -1) >= 0 && (available ?? -1) >= 0 &&
    (used ?? Infinity) + (held ?? Infinity) <= (grant ?? 0) &&
    available === Math.max(0, (grant ?? 0) - (used ?? 0) - (held ?? 0)) &&
    (item.windowState === 'ready' || item.windowState === 'active');
}

async function boundedUsageRequest<T>(path:string):Promise<T>{
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),10000);
  try{return await api.json<T>(path,{signal:controller.signal});}
  finally{clearTimeout(timer);}
}

function componentName(component: string) {
  switch (component) {
    case 'model': return 'Text';
    case 'stt': return 'Speech recognition';
    case 'tts': return 'Speech synthesis';
    case 'voice': return 'Voice';
    case 'browser': return 'Browser';
    case 'sandbox': return 'Sandbox';
    case 'search': return 'Research';
    default: return 'Tools';
  }
}

function activityTime(value: number | string) {
  const milliseconds = typeof value === 'number' ? value * 1000 : Date.parse(value);
  return Number.isFinite(milliseconds) ? new Date(milliseconds).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : 'Recent';
}

function activityTimestamp(value: number | string) {
  return typeof value === 'number' ? value * 1000 : Date.parse(value);
}

function durationLabel(seconds: number) {
  const value = Math.max(0, Math.ceil(seconds));
  if (value < 60) return `${value} sec`;
  const hours = Math.floor(value / 3600), minutes = Math.floor((value % 3600) / 60);
  return hours ? `${hours} hr ${minutes} min` : `${minutes} min`;
}

function recentTasks(items: UsageActivityItem[]) {
  const grouped = new Map<string, { components: Set<string>; microcredits: number; heldMicrocredits:number; grant: number; status:'pending'|'in_progress'|'settled'; createdAt: number | string; estimated: boolean }>();
  for (const item of items) {
    const spent=Number.isFinite(item.microcredits)?Math.max(0,item.microcredits):0;
    const held=Number.isFinite(item.held_micro)?Math.max(0,item.held_micro):0;
    if (!Number.isFinite(item.grant_micro) || item.grant_micro <= 0 || (spent<=0&&held<=0&&item.status==='settled')) continue;
    const key = `${item.root_id || item.id}:${item.period_id}`;
    const group = grouped.get(key);
    const parts = item.components?.length ? item.components : [{ component: item.component, microcredits: item.microcredits, held_micro:item.held_micro, source: item.source }];
    if (group) {
      parts.forEach(part => group.components.add(componentName(part.component)));
      group.microcredits += spent;
      group.heldMicrocredits += held;
      if(item.status==='in_progress'||(item.status==='pending'&&group.status==='settled'))group.status=item.status;
      group.estimated ||= item.source === 'estimated';
      if (activityTimestamp(item.created_at) > activityTimestamp(group.createdAt)) group.createdAt = item.created_at;
    } else {
      grouped.set(key, { components: new Set(parts.map(part => componentName(part.component))), microcredits: spent, heldMicrocredits:held, grant: item.grant_micro, status:item.status||(held>0&&spent<=0?'in_progress':'settled'), createdAt: item.created_at, estimated: item.source === 'estimated' });
    }
  }
  return [...grouped.entries()].map(([id, task]) => ({
    id,
    name: [...task.components].join(' · '),
    activityLabel:usageActivityLabel({used:task.microcredits,held:task.heldMicrocredits,grant:task.grant,status:task.status}),
    createdAt: activityTime(task.createdAt),
    estimated: task.estimated,
  }));
}

function UsageCard({ snapshot, busy, message, onRetry, secondsNow }: {
  snapshot?: UsageSnapshot; busy: boolean; message: string; onRetry: () => void; secondsNow: number;
}) {
  const allowance = snapshot?.allowance;
  const tasks = useMemo(() => recentTasks(snapshot?.activity ?? []), [snapshot?.activity]);
  if (!allowance) {
    return <View style={styles.card}>
      <Text style={styles.heading}>AI allowance</Text>
      <Text style={styles.muted}>Your shared allowance covers new AI work across Open Learn.</Text>
      {busy ? <Text accessibilityRole="text" style={styles.muted}>Loading allowance…</Text> : null}
      {message ? <Text accessibilityRole="alert" style={styles.error}>{message}</Text> : null}
      <Pressable accessibilityRole="button" accessibilityLabel="Retry loading allowance and recent AI work" disabled={busy} onPress={onRetry} style={styles.button}>
        <Text style={styles.buttonText}>{busy ? 'Loading…' : 'Retry'}</Text>
      </Pressable>
    </View>;
  }

  const exactPercent = Math.max(0, Math.min(100, allowance.usedMicrocredits / allowance.grantedMicrocredits * 100));
  const displayedPercent = usedPercentageLabel(exactPercent);
  const progress = Math.max(0, Math.min(100, exactPercent));
  const resetAt = allowance.resetsAt ? new Date(allowance.resetsAt * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) : null;
  const secondsUntilReset = allowance.resetsAt ? Math.max(0, allowance.resetsAt - secondsNow) : null;
  let status = allowance.windowState === 'ready'
    ? 'Your five-hour window starts when you use AI.'
    : resetAt && secondsUntilReset !== null
      ? `Refreshes at ${resetAt} · in ${durationLabel(secondsUntilReset)}.`
      : 'Your allowance refresh time is unavailable.';
  if (allowance.reasonCode === 'usage_reconciliation_pending') status = 'Some activity is still being checked. New AI work is temporarily paused.';
  else if (allowance.reasonCode === 'usage_capacity_unavailable') status = 'AI work is temporarily unavailable while service capacity is checked.';
  else if (allowance.reasonCode === 'usage_window_exhausted' && resetAt) status = `Your allowance is used up for now. It refreshes at ${resetAt}. Your work is saved.`;
  else if (allowance.heldMicrocredits > 0) status += ' Some allowance is reserved for ongoing work.';
  const thresholdMessage = exactPercent >= 95 ? 'Almost all of this window’s allowance has been used.' : exactPercent >= 80 ? 'Most of this window’s allowance has been used.' : '';
  const resetAbsolute = allowance.resetsAt && Number.isFinite(allowance.resetsAt) ? new Date(allowance.resetsAt * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) : null;
  const summary = allowance.windowState === 'ready' ? '0% used' : `${displayedPercent} used`;

  return <View style={styles.card}>
    <Text style={styles.heading}>AI allowance</Text>
    <Text accessibilityRole="text" accessibilityLabel={`AI allowance ${summary}`} style={styles.text}>{summary}</Text>
    <View accessibilityRole="progressbar" accessibilityLabel="AI allowance used" accessibilityValue={{ min: 0, max: 100, now: progress, text: summary }} style={{ height: 10, borderRadius: 8, overflow: 'hidden', backgroundColor: '#404552' }}>
      <View style={{ height: '100%', width: `${progress}%`, backgroundColor: '#80b1ff' }} />
    </View>
    <Text style={styles.muted}>{status}</Text>
    {allowance.windowState === 'active' && resetAbsolute ? <Text style={styles.muted}>Five-hour window · refreshes {resetAbsolute}</Text> : null}
    {thresholdMessage ? <Text accessibilityRole="text" style={styles.muted}>{thresholdMessage}</Text> : null}
    {message ? <Text accessibilityRole="alert" style={styles.error}>{message}</Text> : null}
    <Pressable accessibilityRole="button" accessibilityLabel="Refresh allowance and recent AI work" disabled={busy} onPress={onRetry} style={styles.button}>
      <Text style={styles.buttonText}>{busy ? 'Refreshing…' : 'Refresh usage'}</Text>
    </Pressable>
    <View style={{ height: 1, backgroundColor: '#404552', marginVertical: 4 }} />
    <Text style={styles.heading}>Recent AI work</Text>
    {tasks.length ? tasks.slice(0, 10).map(task => <View key={task.id} style={{ gap: 3, paddingVertical: 4 }}>
      <Text style={styles.text}>{task.name} · {task.activityLabel}</Text>
      <Text style={styles.muted}>{task.createdAt}{task.estimated ? ' · Usage estimate' : ''}</Text>
    </View>) : null}
    {snapshot?.adjustments.map(adjustment=>{
      const percent=adjustment.microcredits*100/allowance.grantedMicrocredits;
      const amount=`${percent>0?'+':''}${percent.toFixed(1).replace(/\.0$/,'')}%`;
      const kind=adjustment.kind.replace(/[_-]+/g,' ');
      return <View key={`adjustment:${adjustment.id}`} style={{gap:3,paddingVertical:4}}><Text style={styles.text}>Usage adjustment · {componentName(adjustment.component)} · {kind} · {amount}</Text><Text style={styles.muted}>{activityTime(adjustment.created_at)}</Text></View>;
    })}
    {!tasks.length&&!snapshot?.adjustments.length?<Text style={styles.muted}>New AI work will appear here after your first request.</Text>:null}
    <Text style={styles.muted}>This percentage is shared across chat, voice, research, browser actions and other supported AI work.</Text>
  </View>;
}

export function MobileSettings({ signedIn }: { signedIn: boolean }) {
  const [tab, setTab] = useState<'usage' | 'updates'>(signedIn ? 'usage' : 'updates');
  const [snapshot, setSnapshot] = useState<UsageSnapshot>();
  const [message, setMessage] = useState(''), [busy, setBusy] = useState(false), [retry, setRetry] = useState(0);
  const [monotonicTick, setMonotonicTick] = useState(monotonicNow());
  const busyRef=useRef(false),snapshotRef=useRef<UsageSnapshot|undefined>(undefined);
  const owner=account()?.owner;
  snapshotRef.current=snapshot;

  useEffect(()=>{
    if(!signedIn||!owner){eventCursor=null;return;}
    if(eventCursor?.owner!==owner)eventCursor={owner,revision:0};
  },[signedIn,owner]);

  useEffect(() => {
    if (tab !== 'usage' || !signedIn) return;
    const requestOwner=account()?.owner;
    if(!requestOwner){setMessage('Sign in again to load account usage.');return;}
    let live = true;
    busyRef.current=true;
    setBusy(true); setMessage('');
    void Promise.allSettled([
      api.json<UsageAllowance>('/v1/usage/allowance'),
      api.json<UsageActivityResponse>('/v1/usage/activity?limit=30'),
    ]).then(([allowanceResult, activityResult]) => {
      if (!live) return;
      if (allowanceResult.status !== 'fulfilled' || !isAllowance(allowanceResult.value)) throw new Error('Usage unavailable.');
      const activity = activityResult.status === 'fulfilled' && Array.isArray(activityResult.value.items) ? activityResult.value.items : [];
      const adjustments = activityResult.status === 'fulfilled' && Array.isArray(activityResult.value.adjustments) ? activityResult.value.adjustments : [];
      const receivedAt = monotonicNow();
      setMonotonicTick(receivedAt);
      setSnapshot({ allowance: allowanceResult.value, activity, adjustments, receivedAt });
      if(eventCursor?.owner!==requestOwner)eventCursor={owner:requestOwner,revision:allowanceResult.value.revision};
      else eventCursor={owner:requestOwner,revision:Math.max(eventCursor.revision,allowanceResult.value.revision)};
      if (activityResult.status === 'rejected' || !Array.isArray(activityResult.value.items)) setMessage('Allowance loaded, but recent AI work could not be loaded. Retry to refresh it.');
    }).catch(() => { if (live) setMessage('Usage could not load. Check your connection and retry.'); })
      .finally(() => { busyRef.current=false;if (live) setBusy(false); });
    return () => { live = false; };
  }, [tab, signedIn, retry]);

  useEffect(()=>{
    if(tab!=='usage'||!signedIn||!owner||!snapshot)return;
    let live=true,timer:ReturnType<typeof setTimeout>|undefined,failures=0,inFlight=false;
    const cadence=15000;
    const schedule=(delay:number)=>{if(live)timer=setTimeout(()=>void poll(),delay);};
    const poll=async()=>{
      if(!live||inFlight)return;
      inFlight=true;
      if(AppState.currentState!=='active'||busyRef.current||eventPolling){inFlight=false;schedule(cadence);return;}
      eventPolling=true;
      try{
        const revision=eventCursor?.owner===owner?eventCursor.revision:(snapshotRef.current?.allowance.revision??0);
        if(eventCursor?.owner!==owner)eventCursor={owner,revision};
        const rawPage=await boundedUsageRequest<unknown>(`/v1/usage/events?afterRevision=${revision}&limit=50`);
        if(!live||owner!==account()?.owner)return;
        const page=parseUsageEventPage(rawPage,revision);
        if(!page)throw new Error('Invalid usage event page.');
        if(page.resnapshotRequired||page.events.length){
          const [allowanceResult,activityResult]=await Promise.allSettled([
            boundedUsageRequest<UsageAllowance>('/v1/usage/allowance'),
            boundedUsageRequest<UsageActivityResponse>('/v1/usage/activity?limit=30'),
          ]);
          if(!live||owner!==account()?.owner)return;
          if(allowanceResult.status!=='fulfilled'||!isAllowance(allowanceResult.value))throw new Error('Invalid allowance snapshot.');
          const allowance=allowanceResult.value;
          const targetRevision=page.resnapshotRequired?page.latestRevision:page.nextRevision;
          if(allowance.revision<targetRevision)throw new Error('Usage snapshot is behind its event feed.');
          const activityOkay=activityResult.status==='fulfilled'&&Array.isArray(activityResult.value.items)&&Array.isArray(activityResult.value.adjustments??[]);
          setSnapshot(previous=>{
            if(!previous)return previous;
            const newer=previous.allowance.revision<allowance.revision;
            if(!newer&&!activityOkay)return previous;
            return{...previous,allowance:newer?allowance:previous.allowance,
              activity:activityOkay?activityResult.value.items:previous.activity,
              adjustments:activityOkay?(activityResult.value.adjustments??[]):previous.adjustments,
              receivedAt:newer?monotonicNow():previous.receivedAt};
          });
          if(!activityOkay)throw new Error('Usage activity could not be refreshed.');
          eventCursor={owner,revision:Math.max(targetRevision,allowance.revision)};
        }
        failures=0;
      }catch{failures=Math.min(5,failures+1);}
      finally{eventPolling=false;inFlight=false;if(live)schedule(Math.min(300000,cadence*2**failures));}
    };
    const subscription=AppState.addEventListener('change',next=>{if(next==='active'&&live){if(timer)clearTimeout(timer);void poll();}});
    void poll();
    return()=>{live=false;if(timer)clearTimeout(timer);subscription.remove();};
  },[tab,signedIn,owner,Boolean(snapshot)]);

  useEffect(() => {
    if (tab !== 'usage' || !signedIn) return;
    const timer = setInterval(() => setMonotonicTick(monotonicNow()), 15000);
    return () => clearInterval(timer);
  }, [tab, signedIn]);

  const secondsNow = snapshot ? snapshot.allowance.serverTime + Math.max(0, monotonicTick - snapshot.receivedAt) / 1000 : 0;
  useEffect(() => {
    const reset = snapshot?.allowance.resetsAt;
    if (tab !== 'usage' || !signedIn || !reset) return;
    const waitMs = Math.max(1000, (reset - secondsNow) * 1000 + 1000);
    const timer = setTimeout(() => setRetry(value => value + 1), Math.min(waitMs, 2147483647));
    return () => clearTimeout(timer);
  }, [snapshot, secondsNow, tab, signedIn]);

  const listing = verifiedStoreUrl(Platform.OS, Platform.OS === 'ios' ? process.env.EXPO_PUBLIC_IOS_STORE_URL : process.env.EXPO_PUBLIC_ANDROID_STORE_URL);
  async function openStore() {
    if (!listing) return;
    setMessage('');
    try { await Linking.openURL(listing); } catch { setMessage('The store could not open. Please try again.'); }
  }

  return <View style={{ gap: 20 }}>
    <View style={styles.row}>{(['usage', 'updates'] as const).filter(item => signedIn || item === 'updates').map(item => <Pressable key={item} accessibilityRole="button" accessibilityState={{ selected: tab === item }} onPress={() => { setMessage(''); setTab(item); }} style={styles.button}><Text style={styles.buttonText}>{item === 'usage' ? 'Usage' : 'Updates'}</Text></Pressable>)}</View>
    {tab === 'usage' ? <UsageCard snapshot={snapshot} busy={busy} message={message} onRetry={() => setRetry(value => value + 1)} secondsNow={secondsNow} /> : <View style={styles.card}><Text style={styles.heading}>Open Learn {APP_VERSION}</Text><Text style={styles.muted}>App updates are delivered through {Platform.OS === 'ios' ? 'the App Store' : 'Google Play'}. Open the listing to see whether an update is available for your device.</Text>{listing ? <Pressable accessibilityRole="button" onPress={() => void openStore()} style={styles.button}><Text style={styles.buttonText}>Open {Platform.OS === 'ios' ? 'App Store' : 'Google Play'}</Text></Pressable> : <Text style={styles.muted}>A store listing is not available for this build. No update check has been performed.</Text>}</View>}
    {tab === 'updates' && message ? <Text accessibilityRole="alert" style={styles.error}>{message}</Text> : null}
  </View>;
}
