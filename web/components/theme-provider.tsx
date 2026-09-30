"use client";

import { ThemeProvider as NextThemesProvider } from 'next-themes';
import { useEffect, type ComponentProps } from 'react';
import { applySettingsPreferences } from '@/lib/settings-preferences';

export function ThemeProvider(props: ComponentProps<typeof NextThemesProvider>) {
  useEffect(() => { applySettingsPreferences(); }, []);
  return <NextThemesProvider {...props} />;
}
