"use client";
import { AccountSettings } from './account-settings';
import { LearnerMemorySettings } from './learner-memory-settings';

import { useEffect, useState, type CSSProperties } from 'react';
import { useTheme } from 'next-themes';
import { ArrowLeft, Bell, BookOpen, Brain, CircleHelp, Database, Download, Gauge, Monitor, Moon, Search, Settings2, Sun } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ProviderSettings } from './provider-settings';
import { UsageSettings } from './usage-settings';
import { ReviewNotificationSettings } from './review-notification-settings';
import {SiteConnections} from './site-connections';
import {AcademicReminderSettings} from './academic-reminder-settings';
import { DataActionsSection, UpdateSection } from './local-data-settings';
import styles from './settings-page.module.css';
import { DEFAULT_SETTINGS, readSettingsPreferences, saveSettingsPreferences, SETTINGS_CHANGED_EVENT, type SettingsPreferences } from '@/lib/settings-preferences';

export type SettingsCategory = 'account' | 'websites' | 'general' | 'learning' | 'audio' | 'usage' | 'api-keys' | 'notifications' | 'memory' | 'data' | 'about' | 'updates';

type CategoryInfo = { id: SettingsCategory; label: string; icon: typeof Settings2; description: string; keywords: string[] };

const CATEGORIES: CategoryInfo[] = [
  { id: 'account', label: 'Account', icon: Monitor, description: 'Your identity, linked devices and connected websites.', keywords: ['Profile', 'Linked devices', 'Link this device', 'Synchronization', 'Connected websites', 'Browser companion', 'Import history', 'Sign in'] },
  { id: 'general', label: 'Appearance', icon: Settings2, description: 'Theme, accent, density and reading comfort for this device.', keywords: ['Theme', 'Light', 'Dark', 'System', 'Accent color', 'Interface density', 'Text size', 'Reduce motion'] },
  { id: 'learning', label: 'Learning', icon: BookOpen, description: 'Default teaching style, quiz choices and class recording.', keywords: ['Default teaching gear', 'Quick', 'Guided', 'Deep', 'Quiz defaults', 'Questions', 'Difficulty', 'Practice mode', 'Time limit', 'Recording defaults', 'Note detail', 'Keep class audio', 'Microphone'] },
  { id: 'usage', label: 'Usage', icon: Gauge, description: 'Recorded tutor activity for your account, from provider reports where available.', keywords: ['Tokens', 'By model', 'By provider', 'Activity'] },
  { id: 'notifications', label: 'Notifications', icon: Bell, description: 'Reminders that help you return to scheduled reviews and deadlines.', keywords: ['Review reminders', 'Quiet hours', 'Academic reminders', 'Reminder inbox'] },
  { id: 'memory', label: 'Memory', icon: Brain, description: 'What your tutor remembers about you, and how to review or forget it.', keywords: ['Add a memory', 'Forget everything', 'Session summaries', 'Buddy settings', 'Sources'] },
  { id: 'data', label: 'Privacy & data', icon: Database, description: 'Manage your account data and saved changes on this device.', keywords: ['Account data', 'Export', 'Delete', 'Drafts', 'Local data'] },
  { id: 'about', label: 'Help', icon: CircleHelp, description: 'Service status, app version and troubleshooting.', keywords: ['AI service', 'Version', 'Platform', 'Troubleshooting', 'Diagnostics'] },
  { id: 'updates', label: 'Updates', icon: Download, description: 'Keep your installed app current.', keywords: ['Version', 'Install update'] },
];
const DESCRIPTIONS = Object.fromEntries(CATEGORIES.map(item => [item.id, item.description])) as Record<SettingsCategory, string>;

/** Categories matching every word of the query, with the setting labels that matched. */
function searchCategories(items: CategoryInfo[], query: string): { item: CategoryInfo; matches: string[] }[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return items.map(item => ({ item, matches: [] }));
  return items.flatMap(item => {
    const haystack = [item.label, item.description, ...item.keywords].join(' ').toLowerCase();
    if (!words.every(word => haystack.includes(word))) return [];
    const matches = item.keywords.filter(keyword => words.some(word => keyword.toLowerCase().includes(word)));
    return [{ item, matches: item.label.toLowerCase().includes(words.join(' ')) ? [] : matches.slice(0, 3) }];
  });
}
const CATEGORY_ALIASES: Partial<Record<SettingsCategory, SettingsCategory>> = { websites: 'account', audio: 'learning', 'api-keys': 'about' };

function hasDesktopPreferences(): boolean {
  if (typeof window === 'undefined') return false;
  return Boolean((window as Window & { formaDesktop?: { preferences?: unknown } }).formaDesktop?.preferences);
}

function downloadDiagnostics(preferences: SettingsPreferences, appVersion: string, platform: string) {
  const report = { app: 'Open Learn', appVersion, platform, generatedAt: new Date().toISOString(), settings: preferences };
  const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `open-learn-diagnostics-${new Date().toISOString().slice(0, 10)}.json`;
  link.click();
  URL.revokeObjectURL(url);
}

/**
 * Full-page settings destination. Categories map one-to-one onto real,
 * already-supported product surfaces; add a category by extending
 * CATEGORIES and rendering its section below. No placeholder settings.
 */
export function SettingsPage({ category: requestedCategory, onCategoryChange, onBack }: {
  category: SettingsCategory;
  onCategoryChange: (category: SettingsCategory) => void;
  onBack: () => void;
}) {
  const category = CATEGORY_ALIASES[requestedCategory] || requestedCategory;
  const [query, setQuery] = useState('');
  const [saved, setSaved] = useState(false);
  const [desktop, setDesktop] = useState(false);
  const [appVersion, setAppVersion] = useState('Web app');
  const [platform, setPlatform] = useState('Browser');
  const [preferences, setPreferences] = useState<SettingsPreferences>(DEFAULT_SETTINGS);
  const { theme, setTheme } = useTheme();
  const selectedTheme = theme ?? 'light';
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDesktop(hasDesktopPreferences());
      const runtime = (window as Window & { formaDesktop?: { version?: string; platform?: string } }).formaDesktop;
      if (runtime?.version) setAppVersion(runtime.version);
      if (runtime?.platform) setPlatform(runtime.platform);
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);
  useEffect(() => {
    const refresh = () => setPreferences(readSettingsPreferences());
    const timer = window.setTimeout(refresh, 0);
    window.addEventListener(SETTINGS_CHANGED_EVENT, refresh);
    return () => { window.clearTimeout(timer); window.removeEventListener(SETTINGS_CHANGED_EVENT, refresh); };
  }, []);
  const available = CATEGORIES.filter(item => desktop || item.id !== 'updates');
  const searching = query.trim().length > 0;
  const results = searchCategories(available, query);
  const updatePreference = <K extends keyof SettingsPreferences>(key: K, value: SettingsPreferences[K]) => { setPreferences(saveSettingsPreferences({ [key]: value })); setSaved(true); };

  return (
    <div className={styles.page}>
      <nav className={styles.nav} aria-label="Settings categories">
        <button type="button" className={styles.back} onClick={onBack}>
          <ArrowLeft size={15} />Back to app
        </button>
        <h2 className={styles.navTitle}>Settings</h2>
        <div className={styles.search} role="search">
          <Search size={15} aria-hidden="true" />
          <input type="search" value={query} placeholder="Search settings" aria-label="Search settings" aria-controls="settings-search-results" onChange={event => setQuery(event.target.value)} onKeyDown={event => { if (event.key === 'Escape' && query) { event.preventDefault(); setQuery(''); } else if (event.key === 'Enter' && results[0]) { event.preventDefault(); onCategoryChange(results[0].item.id); } }} />
        </div>
        <label className={styles.mobilePicker}>Section<select aria-label="Settings section" value={category} onChange={event=>onCategoryChange(event.target.value as SettingsCategory)}>{available.map(item=><option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
        <div id="settings-search-results" className={styles.navList} data-searching={searching || undefined}>
          {searching ? <p className={styles.srOnly} role="status">{results.length ? `${results.length} matching ${results.length === 1 ? 'section' : 'sections'}` : 'No matching settings'}</p> : null}
          {results.map(({ item, matches }) => (
            <button
              key={item.id}
              type="button"
              aria-current={category === item.id ? 'page' : undefined}
              className={styles.navItem + (category === item.id ? ' ' + styles.active : '')}
              onClick={() => onCategoryChange(item.id)}
            >
              <item.icon size={16} />{matches.length ? <span className={styles.navMatch}>{item.label}<small>{matches.join(' · ')}</small></span> : item.label}
            </button>
          ))}
          {searching && !results.length ? <div className={styles.searchEmpty}><p>No settings match “{query.trim()}”.</p><button type="button" onClick={() => setQuery('')}>Clear search</button></div> : null}
        </div>
      </nav>
      <div className={styles.content}>
        <div className={styles.inner} data-density={preferences.density} style={{ '--settings-scale': preferences.textSize === 'large' ? 1.08 : 1 } as CSSProperties}>
          {category === 'account' && <section><h1>Account</h1><p className={styles.lede}>{DESCRIPTIONS.account}</p><div className={styles.card}><AccountSettings section="account" /></div><div className={styles.card}><SiteConnections compact /></div></section>}
          {category === 'general' ? (
            <section aria-label="General settings">
              <h1>Appearance</h1>
              <p className={styles.lede}>{DESCRIPTIONS.general}</p>
              <div className={styles.card}>
                <h2 className={styles.preferenceTitle}>Appearance</h2>
                <p className={styles.preferenceHelp}>Choose a theme and accent. These preferences stay on this device.</p>
                <div className={styles.themeChoices} role="group" aria-label="Color theme">
                  <button type="button" aria-pressed={selectedTheme === 'light'} className={styles.themeChoice + (selectedTheme === 'light' ? ' ' + styles.themeChoiceActive : '')} onClick={() => {setTheme('light');setSaved(true);}}>
                    <Sun size={17} />Light
                  </button>
                  <button type="button" aria-pressed={selectedTheme === 'dark'} className={styles.themeChoice + (selectedTheme === 'dark' ? ' ' + styles.themeChoiceActive : '')} onClick={() => {setTheme('dark');setSaved(true);}}>
                    <Moon size={17} />Dark
                  </button>
                  <button type="button" aria-pressed={selectedTheme === 'system'} className={styles.themeChoice + (selectedTheme === 'system' ? ' ' + styles.themeChoiceActive : '')} onClick={() => {setTheme('system');setSaved(true);}}>
                    <Monitor size={17} />System
                  </button>
                </div>
                <h3 className={styles.subTitle}>Accent color</h3>
                <div className={styles.swatches} role="group" aria-label="Accent color">
                  {(['sage', 'blue', 'violet', 'amber'] as const).map(accent => <button key={accent} type="button" aria-label={`${accent} accent`} aria-pressed={preferences.accent === accent} className={`${styles.swatch} ${styles[`swatch_${accent}`]}${preferences.accent === accent ? ` ${styles.swatchActive}` : ''}`} onClick={() => updatePreference('accent', accent)}>{preferences.accent === accent ? '✓' : null}</button>)}
                </div>
                <div className={styles.preferenceGrid}>
                  <label className={styles.selectRow}>Interface density<select value={preferences.density} onChange={event => updatePreference('density', event.target.value as SettingsPreferences['density'])}><option value="comfortable">Comfortable</option><option value="compact">Compact</option></select></label>
                  <label className={styles.selectRow}>Text size<select value={preferences.textSize} onChange={event => updatePreference('textSize', event.target.value as SettingsPreferences['textSize'])}><option value="default">Default</option><option value="large">Large</option></select></label>
                </div>
                <label className={styles.checkRow}><input type="checkbox" checked={preferences.reduceMotion} onChange={event => updatePreference('reduceMotion', event.target.checked)} /><span><strong>Reduce motion</strong><small>Limit animated transitions throughout the app.</small></span></label>
              </div>
            </section>
          ) : null}
          {category === 'learning' ? (
            <section aria-label="Learning preferences">
              <h1>Learning</h1>
              <p className={styles.lede}>{DESCRIPTIONS.learning} You can still change them any time in a lesson.</p>
              <div className={styles.card}>
                <h2 className={styles.preferenceTitle}>Default teaching gear</h2>
                <p className={styles.preferenceHelp}>This sets the initial explanation depth for new tutor sessions.</p>
                <div className={styles.themeChoices} role="group" aria-label="Default teaching gear">
                  {(['Quick', 'Guided', 'Deep'] as const).map(gear => <button key={gear} type="button" aria-pressed={preferences.defaultGear === gear} className={styles.themeChoice + (preferences.defaultGear === gear ? ` ${styles.themeChoiceActive}` : '')} onClick={() => updatePreference('defaultGear', gear)}>{gear}</button>)}
                </div>
                <p className={styles.muted}>Quick gives a concise answer. Guided builds the idea step by step. Deep adds more context and connections.</p>
                <h2 className={styles.preferenceTitle}>Quiz defaults</h2>
                <p className={styles.preferenceHelp}>New quizzes start with these choices. You can change them before each quiz.</p>
                <div className={styles.preferenceGrid}>
                  <label className={styles.selectRow}>Questions<select value={preferences.quizCount} onChange={event => updatePreference('quizCount', Number(event.target.value) as SettingsPreferences['quizCount'])}>{[3, 5, 10].map(count => <option key={count} value={count}>{count}</option>)}</select></label>
                  <label className={styles.selectRow}>Difficulty<select value={preferences.quizDifficulty} onChange={event => updatePreference('quizDifficulty', event.target.value as SettingsPreferences['quizDifficulty'])}>{[['adaptive', 'Adaptive'], ['foundational', 'Foundational'], ['standard', 'Standard'], ['stretch', 'Stretch']].map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
                  <label className={styles.selectRow}>Practice mode<select value={preferences.quizMode} onChange={event => updatePreference('quizMode', event.target.value as SettingsPreferences['quizMode'])}><option value="topic_drill">Topic drill</option><option value="timed_short_quiz">Timed quiz</option></select></label>
                  {preferences.quizMode === 'timed_short_quiz' ? <label className={styles.selectRow}>Time limit<select value={preferences.quizDurationMinutes} onChange={event => updatePreference('quizDurationMinutes', Number(event.target.value) as SettingsPreferences['quizDurationMinutes'])}>{[5, 10, 15, 20].map(minutes => <option key={minutes} value={minutes}>{minutes} minutes</option>)}</select></label> : null}
                </div>
              </div>
              <div className={styles.card}>
                <h2 className={styles.preferenceTitle}>Recording defaults</h2>
                <p className={styles.preferenceHelp}>How detailed class notes are, and whether class audio is kept.</p>
                <label className={styles.selectRow}>Default note detail<select value={preferences.lectureDepth} onChange={event => updatePreference('lectureDepth', event.target.value as SettingsPreferences['lectureDepth'])}><option value="concise">Concise</option><option value="standard">Standard</option><option value="detailed">Detailed</option></select></label>
                <label className={styles.checkRow}><input type="checkbox" checked={preferences.keepLectureAudio} onChange={event => updatePreference('keepLectureAudio', event.target.checked)} /><span><strong>Keep class audio for playback</strong><small>When off, local recovery audio stays until upload and transcription finish; then the server copy is removed. Notes and transcript remain.</small></span></label>
                <p className={styles.muted}>Microphone access is requested only when you start a recording. Use the recording note to review or remove audio kept for playback.</p>
              </div>
            </section>
          ) : null}
          {category === 'usage' ? (
            <section aria-label="Usage settings">
              <h1>Usage</h1>
              <p className={styles.lede}>{DESCRIPTIONS.usage}</p>
              <div className={styles.group}>
                <div className={styles.card}>
                  <p className={styles.preferenceHelp}>Plan allowances are not configured yet. This page shows recorded activity, not a remaining allowance or a bill.</p><UsageSettings />
                </div>
              </div>
            </section>
          ) : null}
          {category === 'notifications' ? (
            <section aria-label="Notification settings">
              <h1>Notifications</h1>
              <p className={styles.lede}>{DESCRIPTIONS.notifications}</p>
              <div className={styles.card}>
                {desktop ? <ReviewNotificationSettings /> : null}
                <AcademicReminderSettings />
                {!desktop ? <p className={styles.muted}>Delivery permissions belong to each device. Configure desktop review notifications in the installed app.</p> : null}
              </div>
            </section>
          ) : null}
          {category === 'memory' ? (
            <section aria-label="Memory settings">
              <h1>What Open Learn remembers about you</h1>
              <p className={styles.lede}>{DESCRIPTIONS.memory}</p>
              <div className={styles.card}><LearnerMemorySettings /></div>
            </section>
          ) : null}
          {category === 'data' ? (
            <section aria-label="Data and privacy settings">
              <h1>Privacy &amp; data</h1>
              <p className={styles.lede}>{DESCRIPTIONS.data} Device drafts may remain until synchronized or discarded.</p>
              <div className={styles.card}><AccountSettings section="privacy" /></div>
              {(typeof window !== 'undefined' && (window as Window & {formaDesktop?:{serviceMode?:string}}).formaDesktop?.serviceMode === 'local') ? <div className={styles.card}><DataActionsSection /></div> : null}
            </section>
          ) : null}
          {category === 'about' ? (
            <section aria-label="About Open Learn">
              <h1>Help</h1>
              <p className={styles.lede}>{DESCRIPTIONS.about}</p>
              <div className={styles.card}><ProviderSettings /></div>
              <div className={styles.card}>
                <div className={styles.aboutRow}><strong>Open Learn</strong><span>Your Open Learn account</span></div>
                <dl className={styles.aboutFacts}><div><dt>Version</dt><dd>{appVersion}</dd></div><div><dt>Platform</dt><dd>{platform}</dd></div><div><dt>Storage</dt><dd>Account service and device drafts</dd></div></dl>
                <p className={styles.muted}>Preferences are saved on this device. AI credentials are managed securely by Open Learn and are never included in app downloads or learning backups.</p>
                <details className={styles.aboutActions}><summary>Troubleshooting</summary>
                  <Button variant="outline" onClick={() => downloadDiagnostics(preferences, appVersion, platform)}><Download size={15} />Download diagnostics</Button>
                </details>
              </div>
            </section>
          ) : null}
          {category === 'updates' && <section><h1>Updates</h1><p className={styles.lede}>{DESCRIPTIONS.updates}</p><div className={styles.card}>{desktop?<UpdateSection />:<p>The web app updates automatically when you reload. Android and iOS updates are available in the installed app’s Settings.</p>}</div></section>}
          {saved && <p className={styles.saved} role="status">Preferences saved on this device.</p>}
        </div>
      </div>
    </div>
  );
}
