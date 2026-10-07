"use client";
import { useEffect, useState, type ReactNode } from 'react';

export function StudyOverview({ children }: { children: ReactNode }) {
  const [mobile, setMobile] = useState<boolean | null>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const query = window.matchMedia('(max-width: 1023px)');
    const update = () => setMobile(query.matches);
    update();
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  // Don't mount/fetch desktop-only content before the breakpoint is known.
  if (mobile === false) return <>{children}</>;
  return <details className="mobile-today" open={open} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>Today · Your study space</summary>
    {open ? children : null}
  </details>;
}
