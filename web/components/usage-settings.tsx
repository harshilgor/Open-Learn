"use client";

import { useEffect, useState } from 'react';
import { learningApi, friendlyServiceError, type UsageRange, type UsageSummary } from '@/lib/api';
import { UsageAnalyticsView } from './usage-analytics';
import styles from './usage-settings.module.css';

const RANGES: { id: UsageRange; label: string }[] = [
  { id: '7d', label: '7 days' },
  { id: '30d', label: '30 days' },
  { id: 'all', label: 'All time' },
];

export function formatCompactTokens(value: number): string {
  if (!Number.isFinite(value) || value < 0) return '0';
  if (value >= 1_000_000) {
    const rounded = value / 1_000_000;
    return `${rounded >= 100 ? Math.round(rounded) : Math.round(rounded * 10) / 10}M`;
  }
  if (value >= 1_000) {
    const rounded = value / 1_000;
    return `${rounded >= 100 ? Math.round(rounded) : Math.round(rounded * 10) / 10}k`;
  }
  return String(Math.round(value));
}

export function formatFullTokens(value: number): string {
  return new Intl.NumberFormat('en-US').format(Math.max(0, Math.round(value)));
}

function formatCost(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '$0.00';
  if (value < 0.01) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

function shortModel(model: string): string {
  const cleaned = model.split('/').pop() || model;
  return cleaned.length > 34 ? `${cleaned.slice(0, 33)}…` : cleaned;
}

export function UsageSettings() {
  const [tab, setTab] = useState<'overview' | 'analytics'>('overview');
  return (
    <div className={styles.usage}><p className={styles.muted}>Completed tutor generations recorded for this account. Other inference activity may not yet be included. Provider costs below are service diagnostics, not charges to you.</p>
      <div className={styles.tabs} role="tablist" aria-label="Usage views">
        {(['overview', 'analytics'] as const).map(item => (
          <button
            key={item}
            type="button"
            role="tab"
            aria-selected={tab === item}
            className={styles.tab + (tab === item ? ` ${styles.tabActive}` : '')}
            onClick={() => setTab(item)}
          >
            {item === 'overview' ? 'Overview' : 'Analytics'}
          </button>
        ))}
      </div>
      {tab === 'overview' ? <UsageOverview /> : <UsageAnalyticsView />}
    </div>
  );
}

function UsageOverview() {
  const [range, setRange] = useState<UsageRange>('30d');
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [message, setMessage] = useState('');
  const [detail, setDetail] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    learningApi.getUsageSummary(range)
      .then(data => { if (active) { setSummary(data); setMessage(''); setDetail(''); setLoading(false); } })
      .catch((cause: unknown) => {
        if (!active) return;
        const friendly = friendlyServiceError(cause, 'Usage');
        setMessage(friendly.message);
        setDetail(friendly.detail);
        setLoading(false);
      });
    return () => { active = false; };
  }, [range]);

  function selectRange(next: UsageRange) {
    if (next === range) return;
    setLoading(true);
    setMessage('');
    setDetail('');
    setRange(next);
  }

  const totals = summary?.totals;
  const maxDay = Math.max(1, ...(summary?.byDay.map(day => day.totalTokens) || [1]));

  return (
    <div className={styles.usage}>
      <div className={styles.rangeRow} role="group" aria-label="Usage time range">
        {RANGES.map(item => (
          <button
            key={item.id}
            type="button"
            aria-pressed={range === item.id}
            className={styles.rangeButton + (range === item.id ? ` ${styles.rangeActive}` : '')}
            onClick={() => selectRange(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>

      {loading && !summary ? <p className={styles.muted}>Loading usage…</p> : null}
      {message ? <p className={styles.muted} role="status">{message}{detail ? ` ${detail}` : ''}</p> : null}

      {summary && totals ? (
        totals.generations === 0 ? (
          <p className={styles.muted}>No usage yet. Usage appears here after your first model-powered lesson.</p>
        ) : (
          <>
            <dl className={styles.headlines}>
              <div className={styles.headline}>
                <dt>Tokens used</dt>
                <dd title={`${formatFullTokens(totals.totalTokens)} tokens`}>{formatCompactTokens(totals.totalTokens)}</dd>
                <dd className={styles.sub}>
                  {formatCompactTokens(totals.promptTokens)} in · {formatCompactTokens(totals.completionTokens)} out
                  {totals.exactGenerations > 0 ? ` · ${totals.exactGenerations} provider-reported` : ''}
                  {totals.estimatedGenerations > 0 ? ` · ${totals.estimatedGenerations} estimated` : ''}
                </dd>
              </div>
              <div className={styles.headline}>
                <dt>Generations</dt>
                <dd>{formatFullTokens(totals.generations)}</dd>
                <dd className={styles.sub}>{totals.exactGenerations} provider-reported · {totals.estimatedGenerations} estimated</dd>
              </div>
              <div className={styles.headline}>
                <dt>Provider cost</dt>
                <dd>{totals.costIsExact ? formatCost(totals.providerCost) : '—'}</dd>
                <dd className={styles.sub}>{totals.costIsExact ? 'Actual reported cost' : 'No cost reported yet'}</dd>
              </div>
            </dl>

            {summary.byDay.some(day => day.totalTokens > 0) ? (
              <section aria-label="Tokens over time">
                <h2 className={styles.sectionTitle}>Tokens over time</h2>
                <div className={styles.bars} role="img" aria-label={`Token usage over ${range === 'all' ? 'all time' : `the last ${range}`}`}>
                  {summary.byDay.map(day => (
                    <div
                      key={day.date}
                      className={styles.bar}
                      style={{ height: `${Math.max(3, Math.round((day.totalTokens / maxDay) * 100))}%` }}
                      title={`${day.date}: ${formatFullTokens(day.totalTokens)} tokens in ${day.generations} generation${day.generations === 1 ? '' : 's'}`}
                    />
                  ))}
                </div>
              </section>
            ) : null}

            {summary.byModel.length > 0 ? (
              <section aria-label="Usage by model">
                <h2 className={styles.sectionTitle}>By model</h2>
                <ul className={styles.rows}>
                  {summary.byModel.map(entry => (
                    <li key={entry.model} className={styles.row}>
                      <span className={styles.name} title={entry.model}>{shortModel(entry.model)}</span>
                      <span className={styles.value}>{formatCompactTokens(entry.totalTokens)} · {entry.generations}</span>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            {summary.byProvider.length > 1 ? (
              <section aria-label="Usage by provider">
                <h2 className={styles.sectionTitle}>By provider</h2>
                <ul className={styles.rows}>
                  {summary.byProvider.map(entry => (
                    <li key={entry.provider} className={styles.row}>
                      <span className={styles.name}>{entry.provider}</span>
                      <span className={styles.value}>{formatCompactTokens(entry.totalTokens)} · {entry.generations}</span>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </>
        )
      ) : null}
    </div>
  );
}
