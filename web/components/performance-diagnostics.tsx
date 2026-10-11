'use client';

import { useEffect, useState } from 'react';
import { getApiPerformanceSnapshot, getGenerationPerformanceSnapshot } from '@/lib/api-performance';

/** Explicit operator opt-in. Content, account data and credentials are excluded. */
export function PerformanceDiagnostics() {
  const [enabled, setEnabled] = useState(false);
  const [snapshot, setSnapshot] = useState('');
  useEffect(() => { setEnabled(new URLSearchParams(window.location.search).get('performance') === '1'); }, []);
  if (!enabled) return null;
  return <details><summary>Performance diagnostics</summary>
    <button type="button" onClick={() => setSnapshot(JSON.stringify({
      api: getApiPerformanceSnapshot(), generations: getGenerationPerformanceSnapshot(),
    }, null, 2))}>Capture timings</button>
    {snapshot && <textarea aria-label="Content-free performance timings" value={snapshot} readOnly rows={8} style={{ width: '100%' }} />}
  </details>;
}
