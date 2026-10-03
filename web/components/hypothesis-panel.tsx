'use client';
import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { request } from '@/lib/api';
import { Button } from '@/components/ui/button';

type Hypothesis = { id: string; concept_id: string; explanation: string; diagnostic_status: string; revision: number; distinguishing_observation: string; last_reason: string; support: { status: string; supporting_event_ids: string[]; contradicting_event_ids: string[] }; self_reports: { detail: string }[] };
type Recommendation = { action: string; reason: string };

export function HypothesisPanel({ conceptId, refreshKey }: { conceptId?: string; refreshKey?: string }) {
  const router = useRouter();
  const [items, setItems] = useState<Hypothesis[]>([]);
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<Hypothesis[]>([]);
  const reload = useCallback(async () => {
    const query = conceptId ? '?concept_id=' + encodeURIComponent(conceptId) : '';
    const result = await request<{ hypotheses: Hypothesis[] }>('/v1/hypotheses' + query);
    setItems(result.hypotheses);
    if (conceptId) setRecommendation(await request<Recommendation>('/v1/hypotheses/recommendation/' + encodeURIComponent(conceptId)));
  }, [conceptId]);
  useEffect(() => {
    let active = true;
    const load = () => { if (active) void reload().catch(e => { if (active) setError(e instanceof Error ? e.message : 'Could not load possible explanations.'); }); };
    load();
    // Analysis is durable worker work; refresh briefly after an accepted answer.
    const timer = refreshKey ? setTimeout(load, 4000) : undefined;
    return () => { active = false; if (timer) clearTimeout(timer); };
  }, [reload, refreshKey]);

  return <section aria-label="Possible explanations" className="my-5 space-y-4 rounded-xl border border-white/15 p-4">
    <h2 className="text-xl font-semibold">What might explain this answer?</h2><p>These are possibilities, not labels. A short check can help distinguish a mix-up from a slip or unclear wording.</p>
    {!items.length && <p>No active analysis yet. You can continue learning while it is prepared.</p>}
    <Button variant="ghost" onClick={() => void reload().catch(e => setError(String(e)))}>Refresh analysis</Button>
    {recommendation && <p role="status"><strong>Suggested next step: {recommendation.action.replaceAll('_', ' ')}</strong><br />{recommendation.reason}</p>}
    {items.map(item => <article key={item.id} className="space-y-3 border-t border-white/10 pt-4"><h3 className="font-medium">{item.explanation}</h3><p className="text-sm opacity-75">{item.diagnostic_status} · {item.support.status} evidence</p><p>{item.distinguishing_observation}</p>
      <div className="flex flex-wrap gap-2">{['proposed', 'supported'].includes(item.diagnostic_status) && <Button disabled={busy} onClick={async () => { setBusy(true); setError(''); try { const result = await request<{ quiz_id: string }>(`/v1/hypotheses/${item.id}/check`, { method: 'POST' }); router.push('/diagnostics?quiz=' + encodeURIComponent(result.quiz_id)); } catch (e) { setError(String(e)); } finally { setBusy(false); } }}>Try a short check</Button>}
      <Button variant="ghost" onClick={async () => { try { const value = await request<{ revisions: Hypothesis[] }>(`/v1/hypotheses/${item.id}/history`); setHistory(value.revisions); } catch (e) { setError(String(e)); } }}>View history</Button></div>
      <details><summary className="cursor-pointer">Was it a typo or a misread question?</summary><form className="mt-3 space-y-2" onSubmit={async event => { event.preventDefault(); const values = new FormData(event.currentTarget); setBusy(true); try { await request(`/v1/hypotheses/${item.id}/self-report`, { method: 'POST', body: JSON.stringify({ explanation: values.get('explanation'), detail: values.get('detail') }) }); await reload(); } catch (e) { setError(String(e)); } finally { setBusy(false); } }}><label className="block">Your explanation<select name="explanation" className="ml-2 rounded border bg-transparent p-2"><option value="misread">I misread it</option><option value="typo">It was a typo</option><option value="arithmetic_slip">An arithmetic slip</option><option value="other">Something else</option></select></label><label className="block">What happened?<textarea name="detail" required maxLength={1500} className="block w-full rounded border border-white/20 bg-transparent p-2" /></label><Button disabled={busy}>Save my explanation</Button><p className="text-sm opacity-70">Saved as your explanation alongside the answer evidence.</p></form></details>
      {item.self_reports.map((report, index) => <p key={index} className="text-sm">Your explanation: {report.detail}</p>)}
    </article>)}
    {history.length > 0 && <section className="space-y-2 rounded border border-white/20 p-3"><h3>Hypothesis history</h3>{history.map(item => <p key={item.revision}>Revision {item.revision}: {item.diagnostic_status} · {item.last_reason.replaceAll('_', ' ')} · {item.support.supporting_event_ids.length} supporting, {item.support.contradicting_event_ids.length} contradicting observations</p>)}<Button variant="ghost" onClick={() => setHistory([])}>Close history</Button></section>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
