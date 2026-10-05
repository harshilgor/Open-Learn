import { useEffect, useState } from 'react';
import { Linking, Platform, Pressable, Text, View } from 'react-native';
import { api } from './account';
import { styles } from './theme';
import { APP_VERSION, verifiedStoreUrl } from './release';

export function MobileSettings({ signedIn }: { signedIn: boolean }) {
  const [tab, setTab] = useState<'usage' | 'updates'>(signedIn ? 'usage' : 'updates');
  const [usage, setUsage] = useState<{ totals: { totalTokens: number; generations: number; estimatedGenerations: number } }>();
  const [message, setMessage] = useState(''), [busy, setBusy] = useState(false), [retry, setRetry] = useState(0);
  useEffect(() => {
    if (tab !== 'usage' || !signedIn) return;
    let live = true; setBusy(true); setMessage('');
    void api.json<typeof usage>('/v1/usage/summary?range=30d').then(value => { if (live) setUsage(value); }).catch(() => { if (live) setMessage('Usage could not load. Check your connection and retry.'); }).finally(() => { if (live) setBusy(false); });
    return () => { live = false; };
  }, [tab, signedIn, retry]);
  const listing = verifiedStoreUrl(Platform.OS, Platform.OS === 'ios' ? process.env.EXPO_PUBLIC_IOS_STORE_URL : process.env.EXPO_PUBLIC_ANDROID_STORE_URL);
  async function openStore() {
    if (!listing) return;
    setMessage('');
    try { await Linking.openURL(listing); } catch { setMessage('The store could not open. Please try again.'); }
  }
  return <View style={{ gap: 20 }}>
    <View style={styles.row}>{(['usage', 'updates'] as const).filter(item => signedIn || item === 'updates').map(item => <Pressable key={item} accessibilityRole="button" accessibilityState={{ selected: tab === item }} onPress={() => { setMessage(''); setTab(item); }} style={styles.button}><Text style={styles.buttonText}>{item === 'usage' ? 'Usage' : 'Updates'}</Text></Pressable>)}</View>
    {tab === 'usage' ? <View style={styles.card}><Text style={styles.heading}>Recorded activity · last 30 days</Text><Text style={styles.muted}>Completed tutor generations for this account. Plan allowances are not configured yet; these totals are not a remaining balance or a bill.</Text>{usage ? <><Text style={styles.text}>{usage.totals.totalTokens.toLocaleString()} tokens</Text><Text style={styles.text}>{usage.totals.generations.toLocaleString()} generations</Text>{usage.totals.estimatedGenerations > 0 && <Text style={styles.muted}>Some usage is estimated.</Text>}</> : busy ? <Text style={styles.muted}>Loading usage…</Text> : null}<Pressable accessibilityRole="button" disabled={busy} onPress={() => setRetry(value => value + 1)} style={styles.button}><Text style={styles.buttonText}>{busy ? 'Loading…' : 'Refresh usage'}</Text></Pressable></View> : <View style={styles.card}><Text style={styles.heading}>Open Learn {APP_VERSION}</Text><Text style={styles.muted}>App updates are delivered through {Platform.OS === 'ios' ? 'the App Store' : 'Google Play'}. Open the listing to see whether an update is available for your device.</Text>{listing ? <Pressable accessibilityRole="button" onPress={() => void openStore()} style={styles.button}><Text style={styles.buttonText}>Open {Platform.OS === 'ios' ? 'App Store' : 'Google Play'}</Text></Pressable> : <Text style={styles.muted}>A store listing is not available for this build. No update check has been performed.</Text>}</View>}
    {message ? <Text accessibilityRole="alert" style={styles.error}>{message}</Text> : null}
  </View>;
}
