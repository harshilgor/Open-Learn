"use client";

import { useReducedMotion } from 'motion/react';
import { useSettingsPreferences } from '@/lib/settings-preferences';

export function useAppReducedMotion() {
  const systemPreference = useReducedMotion();
  const settings = useSettingsPreferences();
  return systemPreference || settings.reduceMotion;
}
