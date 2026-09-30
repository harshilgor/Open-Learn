"use client";

import { useSyncExternalStore } from 'react';
import type { Gear } from '@/lib/api';

export type SettingsPreferences = {
  accent: 'sage' | 'blue' | 'violet' | 'amber';
  density: 'comfortable' | 'compact';
  textSize: 'default' | 'large';
  reduceMotion: boolean;
  defaultGear: Gear;
  quizCount: 3 | 5 | 10;
  quizDifficulty: 'adaptive' | 'foundational' | 'standard' | 'stretch';
  quizMode: 'topic_drill' | 'timed_short_quiz';
  quizDurationMinutes: 5 | 10 | 15 | 20;
  lectureDepth: 'concise' | 'standard' | 'detailed';
  keepLectureAudio: boolean;
};

const STORAGE_KEY = 'forma-settings-preferences-v1';
export const SETTINGS_CHANGED_EVENT = 'forma-settings-preferences-changed';
export const DEFAULT_SETTINGS: SettingsPreferences = {
  accent: 'sage', density: 'comfortable', textSize: 'default', reduceMotion: false,
  defaultGear: 'Quick', quizCount: 5, quizDifficulty: 'adaptive', quizMode: 'topic_drill', quizDurationMinutes: 10,
  lectureDepth: 'standard', keepLectureAudio: true,
};

let settingsSnapshot: SettingsPreferences = DEFAULT_SETTINGS;
let snapshotLoaded = false;

function valid(value: unknown): value is Partial<SettingsPreferences> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

export function readSettingsPreferences(): SettingsPreferences {
  if (typeof window === 'undefined') return DEFAULT_SETTINGS;
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || '{}');
    if (!valid(parsed)) return DEFAULT_SETTINGS;
    return {
      accent: ['sage', 'blue', 'violet', 'amber'].includes(String(parsed.accent)) ? parsed.accent as SettingsPreferences['accent'] : DEFAULT_SETTINGS.accent,
      density: parsed.density === 'compact' ? 'compact' : 'comfortable',
      textSize: parsed.textSize === 'large' ? 'large' : 'default',
      reduceMotion: parsed.reduceMotion === true,
      defaultGear: ['Quick', 'Guided', 'Deep'].includes(String(parsed.defaultGear)) ? parsed.defaultGear as Gear : DEFAULT_SETTINGS.defaultGear,
      quizCount: [3, 5, 10].includes(Number(parsed.quizCount)) ? Number(parsed.quizCount) as SettingsPreferences['quizCount'] : DEFAULT_SETTINGS.quizCount,
      quizDifficulty: ['adaptive', 'foundational', 'standard', 'stretch'].includes(String(parsed.quizDifficulty)) ? parsed.quizDifficulty as SettingsPreferences['quizDifficulty'] : DEFAULT_SETTINGS.quizDifficulty,
      quizMode: parsed.quizMode === 'timed_short_quiz' ? 'timed_short_quiz' : 'topic_drill',
      quizDurationMinutes: [5, 10, 15, 20].includes(Number(parsed.quizDurationMinutes)) ? Number(parsed.quizDurationMinutes) as SettingsPreferences['quizDurationMinutes'] : DEFAULT_SETTINGS.quizDurationMinutes,
      lectureDepth: ['concise', 'standard', 'detailed'].includes(String(parsed.lectureDepth)) ? parsed.lectureDepth as SettingsPreferences['lectureDepth'] : DEFAULT_SETTINGS.lectureDepth,
      keepLectureAudio: parsed.keepLectureAudio !== false,
    };
  } catch { return DEFAULT_SETTINGS; }
}

function subscribe(callback: () => void) {
  if (typeof window === 'undefined') return () => undefined;
  const changed = () => callback();
  const storageChanged = () => { settingsSnapshot = readSettingsPreferences(); snapshotLoaded = true; callback(); };
  window.addEventListener(SETTINGS_CHANGED_EVENT, changed);
  window.addEventListener('storage', storageChanged);
  return () => { window.removeEventListener(SETTINGS_CHANGED_EVENT, changed); window.removeEventListener('storage', storageChanged); };
}

function getSnapshot() {
  if (!snapshotLoaded) { settingsSnapshot = readSettingsPreferences(); snapshotLoaded = true; }
  return settingsSnapshot;
}

export function useSettingsPreferences() {
  return useSyncExternalStore(subscribe, getSnapshot, () => DEFAULT_SETTINGS);
}

export function applySettingsPreferences(preferences = readSettingsPreferences()) {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  root.dataset.accent = preferences.accent;
  root.dataset.density = preferences.density;
  root.dataset.textSize = preferences.textSize;
  root.dataset.reduceMotion = String(preferences.reduceMotion);
}

export function saveSettingsPreferences(patch: Partial<SettingsPreferences>): SettingsPreferences {
  const next = { ...readSettingsPreferences(), ...patch };
  try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next)); } catch { /* The current screen still applies the selected preference. */ }
  settingsSnapshot = next;
  snapshotLoaded = true;
  applySettingsPreferences(next);
  window.dispatchEvent(new CustomEvent(SETTINGS_CHANGED_EVENT, { detail: next }));
  return next;
}
