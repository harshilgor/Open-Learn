"use client";
import { useState, type ReactNode } from 'react';

/** Mount when first opened, then retain drafts and editor state while hidden. */
export function DeferredWorkspace({ active, children }: { active: boolean; children: ReactNode }) {
  const [opened, setOpened] = useState(active);
  // A guarded render-time adjustment avoids an extra effect/paint on first open.
  if (active && !opened) setOpened(true);
  return active || opened ? <>{children}</> : null;
}
