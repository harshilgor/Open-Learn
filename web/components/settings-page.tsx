"use client";

import { useEffect, useState, type CSSProperties } from 'react';
import { useTheme } from 'next-themes';
import { ArrowLeft, Bell, BookOpen, CircleHelp, Database, Download, ExternalLink, Gauge, Headphones, KeyRound, Monitor, Moon, Settings2, Sun } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ProviderSettings } from './provider-settings';
import { UsageSettings } from './usage-settings';
import { ReviewNotificationSettings } from './review-notification-settings';
import { DataActionsSection, UpdateSection } from './local-data-settings';
import styles from './settings-page.module.css';
import { DEFAULT_SETTINGS, readSettingsPreferences, saveSettingsPreferences, SETTINGS_CHANGED_EVENT, type SettingsPreferences } from '@/lib/settings-preferences';

export type SettingsCategory = 'general' | 'learning' | 'audio' | 'usage' | 'api-keys' | 'notifications' | 'data' | 'about';

const CATEGORIES: { id: SettingsCategory; label: string; icon: typeof Settings2 }[] = [
  { id: 'general', label: 'General', icon: Settings2 },
  { id: 'learning', label: 'Learning', icon: BookOpen },
  { id: 'audio', label: 'Audio & recordings', icon: Headphones },
  { id: 'usage', label: 'Usage', icon: Gauge },
  { id: 'api-keys', label: 'API keys', icon: KeyRound },
  { id: 'notifications', label: 'Notifications', icon: Bell },
  { id: 'data', label: 'Data & privacy', icon: Database },
  { id: 'about', label: 'About', icon: CircleHelp },
];

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
export function SettingsPage({ category, onCategoryChange, onBack }: {
  category: SettingsCategory;
  onCategoryChange: (category: SettingsCategory) => void;
  onBack: () => void;
}) {
  const [desktop, setDesktop] = useState(false);
  const [appVersion, setAppVersion] = useState('Web app');
  const [platform, setPlatform] = useState('Browser');
  const [preferences, setPreferences] = useState<SettingsPreferences>(DEFAULT_SETTINGS);
  const { theme, setTheme } = useTheme();
  const selectedTheme = theme ?? 'system';
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
  const updatePreference = <K extends keyof SettingsPreferences>(key: K, value: SettingsPreferences[K]) => setPreferences(saveSettingsPreferences({ [key]: value }));

  return (
    <div className={styles.page}>
      <nav className={styles.nav} aria-label="Settings categories">
        <button type="button" className={styles.back} onClick={onBack}>
          <ArrowLeft size={15} />Back to app
        </button>
        {CATEGORIES.map(item => (
          <button
            key={item.id}
            type="button"
            aria-current={category === item.id ? 'page' : undefined}
            className={styles.navItem + (category === item.id ? ' ' + styles.active : '')}
            onClick={() => onCategoryChange(item.id)}
          >
            <item.icon size={16} />{item.label}
          </button>
        ))}
      </nav>
      <div className={styles.content}>
        <div className={styles.inner} data-density={preferences.density} style={{ '--settings-scale': preferences.textSize === 'large' ? 1.08 : 1 } as CSSProperties}>
          {category === 'general' ? (
            <section aria-label="General settings">
              <h1>General</h1>
              <p className={styles.lede}>Set the appearance and reading comfort for this device.</p>
              <div className={styles.card}>
                <h2 className={styles.preferenceTitle}>Appearance</h2>
                <p className={styles.preferenceHelp}>Choose a theme and accent. These preferences stay on this device.</p>
                <div className={styles.themeChoices} role="group" aria-label="Color theme">
                  <button type="button" aria-pressed={selectedTheme === 'light'} className={styles.themeChoice + (selectedTheme === 'light' ? ' ' + styles.themeChoiceActive : '')} onClick={() => setTheme('light')}>
                    <Sun size={17} />Light
                  </button>
                  <button type="button" aria-pressed={selectedTheme === 'dark'} className={styles.themeChoice + (selectedTheme === 'dark' ? ' ' + styles.themeChoiceActive : '')} onClick={() => setTheme('dark')}>
                    <Moon size={17} />Dark
                  </button>
                  <button type="button" aria-pressed={selectedTheme === 'system'} className={styles.themeChoice + (selectedTheme === 'system' ? ' ' + styles.themeChoiceActive : '')} onClick={() => setTheme('system')}>
                    <Monitor size={17} />System
                  </button>
                </div>
                <h3 className={styles.subTitle}>Accent color</h3>
                <div className={styles.swatches} role="group" aria-label="Accent color">
                  {(['sage', 'blue', 'violet', 'amber'] as const).map(accent => <button key={accent} type="button" aria-label={`${accent} accent`} aria-pressed={preferences.accent === accent} className={`${styles.swatch} ${styles[`swatch_${accent}`]}${preferences.accent === accent ? ` ${styles.swatchActive}` : ''}`} onClick={() => updatePreference('accent', accent)} />)}
                </div>
                <div className={styles.preferenceGrid}>
                  <label className={styles.selectRow}>Interface density<select value={preferences.density} onChange={event => updatePreference('density', event.target.value as SettingsPreferences['density'])}><option value="comfortable">Comfortable</option><option value="compact">Compact</option></select></label>
                  <label className={styles.selectRow}>Text size<select value={preferences.textSize} onChange={event => updatePreference('textSize', event.target.value as SettingsPreferences['textSize'])}><option value="default">Default</option><option value="large">Large</option></select></label>
                </div>
                <label className={styles.checkRow}><input type="checkbox" checked={preferences.reduceMotion} onChange={event => updatePreference('reduceMotion', event.target.checked)} /><span><strong>Reduce motion</strong><small>Limit animated transitions throughout the app.</small></span></label>
              </div>
              <div className={styles.group}>
                <UpdateSection />
                {!desktop ? <p className={styles.muted}>Update checks are available in the desktop app.</p> : null}
              </div>
            </section>
          ) : null}
          {category === 'learning' ? (
            <section aria-label="Learning preferences">
              <h1>Learning</h1>
              <p className={styles.lede}>Choose your starting style. You can still change it any time in a lesson.</p>
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
            </section>
          ) : null}
          {category === 'audio' ? (
            <section aria-label="Audio and recording preferences">
              <h1>Audio &amp; recordings</h1>
              <p className={styles.lede}>Set defaults for future class recordings. Existing recordings keep their current settings.</p>
              <div className={styles.card}>
                <h2 className={styles.preferenceTitle}>Recording defaults</h2>
                <label className={styles.selectRow}>Default note detail<select value={preferences.lectureDepth} onChange={event => updatePreference('lectureDepth', event.target.value as SettingsPreferences['lectureDepth'])}><option value="concise">Concise</option><option value="standard">Standard</option><option value="detailed">Detailed</option></select></label>
                <label className={styles.checkRow}><input type="checkbox" checked={preferences.keepLectureAudio} onChange={event => updatePreference('keepLectureAudio', event.target.checked)} /><span><strong>Keep class audio for playback</strong><small>When off, the app removes server audio after notes are generated. Unsynced browser audio remains until processing completes.</small></span></label>
                <p className={styles.muted}>Microphone access is requested only when you start a recording. Use the recording note to review or remove audio kept for playback.</p>
              </div>
            </section>
          ) : null}
          {category === 'usage' ? (
            <section aria-label="Usage settings">
              <h1>Usage</h1>
              <p className={styles.lede}>Tokens and generations used on this device, measured from provider-reported usage where available.</p>
              <div className={styles.group}>
                <div className={styles.card}>
                  <UsageSettings />
                </div>
              </div>
            </section>
          ) : null}
          {category === 'api-keys' ? (
            <section aria-label="API key settings">
              <h1>API keys</h1>
              <p className={styles.lede}>Connect a model provider for AI-powered lessons, quizzes, and lecture transcription. Provider credentials are stored by this app’s local service.</p>
              <div className={styles.group}>
                <div className={styles.card}>
                  <ProviderSettings />
                </div>
              </div>
            </section>
          ) : null}
          {category === 'notifications' ? (
            <section aria-label="Notification settings">
              <h1>Notifications</h1>
              <p className={styles.lede}>Reminders that help you return to scheduled reviews.</p>
              <div className={styles.card}>
                <ReviewNotificationSettings />
                {!desktop ? <p className={styles.muted}>Review reminders are available in the desktop app. Notifications stay on this device.</p> : null}
              </div>
            </section>
          ) : null}
          {category === 'data' ? (
            <section aria-label="Data and privacy settings">
              <h1>Data &amp; privacy</h1>
              <p className={styles.lede}>{desktop ? 'Your lessons, notes, recordings, and review state are stored by this desktop app.' : 'Your learning data is stored by the connected local service. Export or remove it at any time.'}</p>
              <div className={styles.card}>
                <DataActionsSection />
              </div>
            </section>
          ) : null}
          {category === 'about' ? (
            <section aria-label="About Open Learn">
              <h1>About</h1>
              <p className={styles.lede}>A local-first learning environment for guided study, practice, and review.</p>
              <div className={styles.card}>
                <div className={styles.aboutRow}><strong>Open Learn</strong><span>Personal · On this device</span></div>
                <dl className={styles.aboutFacts}><div><dt>Version</dt><dd>{appVersion}</dd></div><div><dt>Platform</dt><dd>{platform}</dd></div><div><dt>Storage</dt><dd>{desktop ? 'Desktop app data folder' : 'Connected local service'}</dd></div></dl>
                <p className={styles.muted}>Preferences are saved on this device. Model credentials stay in the desktop credential store or local service configuration and are never included in learning backups.</p>
                <div className={styles.aboutActions}>
                  <Button variant="outline" onClick={() => downloadDiagnostics(preferences, appVersion, platform)}><Download size={15} />Download diagnostics</Button>
                  <a href="https://github.com/harshilgor/Open-Learn/blob/main/CHANGELOG.md" target="_blank" rel="noreferrer">Release notes<ExternalLink size={14} /></a>
                  <a href="https://github.com/harshilgor/Open-Learn/blob/main/docs/INSTALL.md" target="_blank" rel="noreferrer">Help and setup<ExternalLink size={14} /></a>
                  <a href="https://github.com/harshilgor/Open-Learn/issues/new" target="_blank" rel="noreferrer">Send feedback<ExternalLink size={14} /></a>
                </div>
              </div>
            </section>
          ) : null}
        </div>
      </div>
    </div>
  );
}
