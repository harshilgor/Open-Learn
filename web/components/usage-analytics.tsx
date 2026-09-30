"use client";

import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronRight } from 'lucide-react';
import { learningApi, friendlyServiceError, type AnalyticsDimension, type UsageAnalytics } from '@/lib/api';
import { formatCompactTokens, formatFullTokens } from './usage-settings';
import styles from './usage-analytics.module.css';

const SERIES_COLORS = ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)', 'var(--chart-4)', 'var(--chart-5)', 'var(--chart-6)'];

const DIMENSIONS: { id: AnalyticsDimension; label: string }[] = [
  { id: 'mode', label: 'By feature' },
  { id: 'model', label: 'By model' },
  { id: 'provider', label: 'By provider' },
  { id: 'course', label: 'By course' },
];

function colorFor(index: number): string {
  return SERIES_COLORS[index % SERIES_COLORS.length];
}

function shortKey(key: string): string {
  const cleaned = key.split('/').pop() || key;
  return cleaned.length > 26 ? `${cleaned.slice(0, 25)}…` : cleaned;
}

function formatDay(iso: string): string {
  const [year, month, day] = iso.split('-').map(Number);
  if (!year || !month || !day) return iso;
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' });
}

function formatDayLong(iso: string): string {
  const [year, month, day] = iso.split('-').map(Number);
  if (!year || !month || !day) return iso;
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' });
}

function formatCost(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '—';
  if (value < 0.01) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

function HistoryChart({ data, dimension }: { data: UsageAnalytics; dimension: AnalyticsDimension }) {
  const [hover, setHover] = useState<number | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const maxDay = Math.max(1, ...data.days.map(day => day.totalTokens));
  const hoverDay = hover !== null ? data.days[hover] : null;
  const dimensionLabel = DIMENSIONS.find(item => item.id === dimension)?.label || 'By feature';

  return (
    <div>
      <div className={styles.stackBars} ref={wrapRef}>
        {data.days.map((day, index) => {
          const height = Math.max(2, Math.round((day.totalTokens / maxDay) * 100));
          return (
            <div
              key={day.date}
              className={styles.stackCol + (hover === index ? ` ${styles.stackColActive}` : '')}
              style={{ height: `${height}%` }}
              onMouseEnter={() => setHover(index)}
              onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(index)}
              onBlur={() => setHover(null)}
              tabIndex={0}
              role="img"
              aria-label={`${formatDayLong(day.date)}: ${formatFullTokens(day.totalTokens)} tokens in ${day.generations} generations`}
            >
              {data.series.map((entry, seriesIndex) => {
                const value = entry.points[index] || 0;
                if (value <= 0) return null;
                return (
                  <div
                    key={entry.key}
                    className={styles.stackSeg}
                    style={{ flexGrow: value, background: colorFor(seriesIndex) }}
                  />
                );
              })}
            </div>
          );
        })}
        {hoverDay ? (
          <div className={styles.tooltip} role="status">
            <div className={styles.tooltipTitle}>Share of total usage</div>
            <div className={styles.tooltipDate}>{formatDayLong(hoverDay.date)}</div>
            {data.series.map((entry, seriesIndex) => {
              const value = entry.points[hover as number] || 0;
              if (value <= 0) return null;
              const share = hoverDay.totalTokens > 0 ? (value / hoverDay.totalTokens) * 100 : 0;
              return (
                <div key={entry.key} className={styles.tooltipRow}>
                  <span className={styles.dot} style={{ background: colorFor(seriesIndex) }} />
                  <span className={styles.tooltipKey}>{shortKey(entry.key)}</span>
                  <span className={styles.tooltipValue}>{share.toFixed(share >= 10 ? 1 : 2)}%</span>
                </div>
              );
            })}
          </div>
        ) : null}
      </div>
      <div className={styles.axisRow} aria-hidden="true">
        <span>{formatDay(data.days[0]?.date || '')}</span>
        <span>{formatDay(data.days[Math.floor(data.days.length / 2)]?.date || '')}</span>
        <span>{formatDay(data.days[data.days.length - 1]?.date || '')}</span>
      </div>
      <ul className={styles.legend}>
        {data.series.map((entry, seriesIndex) => (
          <li key={entry.key} title={`${formatFullTokens(entry.totalTokens)} tokens in ${entry.generations} generations`}>
            <span className={styles.dot} style={{ background: colorFor(seriesIndex) }} />
            <span className={styles.legendKey}>{shortKey(entry.key)}</span>
            <strong>{entry.sharePct.toFixed(1)}%</strong>
          </li>
        ))}
      </ul>
      <p className={styles.muted}>Grouped {dimensionLabel.toLowerCase()} · hover a day for its share breakdown.</p>
    </div>
  );
}

function TrendChart({ days, lines, formatValue }: {
  days: string[];
  lines: { key: string; color: string; values: number[] }[];
  formatValue: (value: number) => string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const width = 640;
  const height = 180;
  const padLeft = 36;
  const padRight = 8;
  const padTop = 10;
  const padBottom = 22;
  const maxValue = Math.max(1, ...lines.flatMap(line => line.values));
  const niceMax = maxValue <= 4 ? Math.max(4, maxValue) : Math.ceil(maxValue * 1.1);
  const x = (index: number) => padLeft + (index / Math.max(1, days.length - 1)) * (width - padLeft - padRight);
  const y = (value: number) => padTop + (1 - value / niceMax) * (height - padTop - padBottom);
  const ticks = useMemo(() => {
    if (niceMax <= 4) return Array.from({ length: niceMax + 1 }, (_, i) => i);
    const step = Math.max(1, Math.round(niceMax / 4));
    const result = [];
    for (let value = 0; value <= niceMax; value += step) result.push(value);
    return result;
  }, [niceMax]);

  function onMove(event: React.MouseEvent) {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;
    const px = ((event.clientX - rect.left) / rect.width) * width;
    const ratio = (px - padLeft) / (width - padLeft - padRight);
    const index = Math.round(ratio * (days.length - 1));
    setHover(Math.max(0, Math.min(days.length - 1, index)));
  }

  return (
    <div className={styles.trendWrap}>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${width} ${height}`}
        className={styles.trendSvg}
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
        role="img"
        aria-label="Usage trend over time"
      >
        {ticks.map(tick => (
          <g key={tick}>
            <line x1={padLeft} x2={width - padRight} y1={y(tick)} y2={y(tick)} className={styles.grid} />
            <text x={padLeft - 6} y={y(tick) + 4} textAnchor="end" className={styles.tick}>{formatCompactTokens(tick)}</text>
          </g>
        ))}
        {[0, Math.floor((days.length - 1) / 2), days.length - 1].map(index => (
          <text key={index} x={x(index)} y={height - 6} textAnchor="middle" className={styles.tick}>
            {formatDay(days[index] || '')}
          </text>
        ))}
        {lines.map(line => (
          <polyline
            key={line.key}
            points={line.values.map((value, index) => `${x(index)},${y(value)}`).join(' ')}
            fill="none"
            stroke={line.color}
            strokeWidth={hover === null ? 2 : 1.5}
            strokeLinejoin="round"
            strokeLinecap="round"
            opacity={hover === null ? 1 : 0.9}
          >
            <title>{`${line.key}: ${formatValue(line.values.reduce((a, b) => a + b, 0))} total`}</title>
          </polyline>
        ))}
        {hover !== null ? (
          <g>
            <line x1={x(hover)} x2={x(hover)} y1={padTop} y2={height - padBottom} className={styles.guide} />
            {lines.map(line => (
              <circle key={line.key} cx={x(hover)} cy={y(line.values[hover] || 0)} r={3.5} fill={line.color} stroke="var(--card)" strokeWidth={1.5} />
            ))}
          </g>
        ) : null}
      </svg>
      {hover !== null ? (
        <div className={styles.tooltip} role="status">
          <div className={styles.tooltipDate}>{formatDayLong(days[hover] || '')}</div>
          {lines.map(line => (
            <div key={line.key} className={styles.tooltipRow}>
              <span className={styles.dot} style={{ background: line.color }} />
              <span className={styles.tooltipKey}>{shortKey(line.key)}</span>
              <span className={styles.tooltipValue}>{formatValue(line.values[hover] || 0)}</span>
            </div>
          ))}
        </div>
      ) : null}
      <ul className={styles.legend}>
        {lines.map(line => (
          <li key={line.key}>
            <span className={styles.dot} style={{ background: line.color }} />
            <span className={styles.legendKey}>{shortKey(line.key)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function TopSessions({ data }: { data: UsageAnalytics }) {
  const [open, setOpen] = useState<string | null>(null);
  if (data.topSessions.length === 0) return <p className={styles.muted}>No sessions in this range yet.</p>;
  return (
    <ul className={styles.sessions}>
      <li className={styles.sessionHead} aria-hidden="true">
        <span>Session</span>
        <span>Tokens used</span>
      </li>
      {data.topSessions.map(session => {
        const expanded = open === session.sessionId;
        return (
          <li key={session.sessionId} className={styles.session}>
            <button
              type="button"
              className={styles.sessionRow}
              aria-expanded={expanded}
              onClick={() => setOpen(expanded ? null : session.sessionId)}
            >
              <ChevronRight size={15} className={styles.chevron + (expanded ? ` ${styles.chevronOpen}` : '')} />
              <span className={styles.sessionTitle} title={session.sessionId}>{session.title}</span>
              <span className={styles.sessionTokens}>{formatCompactTokens(session.totalTokens)}</span>
            </button>
            {expanded ? (
              <div className={styles.sessionDetail}>
                <div className={styles.sessionMeta}>
                  <span>{session.generations} generation{session.generations === 1 ? '' : 's'}</span>
                  <span>{session.costIsExact ? `${formatCost(session.providerCost)} actual` : 'Cost not reported'}</span>
                  {session.lastActive ? <span>Active {formatDayLong(session.lastActive.slice(0, 10))}</span> : null}
                </div>
                <ul className={styles.rows}>
                  {session.byModel.map(entry => (
                    <li key={entry.model} className={styles.row}>
                      <span className={styles.name} title={entry.model}>{shortKey(entry.model)}</span>
                      <span className={styles.value}>{formatCompactTokens(entry.totalTokens)} · {entry.generations}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

export function UsageAnalyticsView() {
  const [range, setRange] = useState<'7d' | '30d'>('7d');
  const [dimension, setDimension] = useState<AnalyticsDimension>('mode');
  const [data, setData] = useState<UsageAnalytics | null>(null);
  const [message, setMessage] = useState('');
  const [detail, setDetail] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    learningApi.getUsageAnalytics(range, dimension, 5)
      .then(result => { if (active) { setData(result); setMessage(''); setDetail(''); setLoading(false); } })
      .catch((cause: unknown) => {
        if (!active) return;
        const friendly = friendlyServiceError(cause, 'Analytics');
        setMessage(friendly.message);
        setDetail(friendly.detail);
        setLoading(false);
      });
    return () => { active = false; };
  }, [range, dimension]);

  function selectRange(next: '7d' | '30d') {
    if (next === range) return;
    setLoading(true);
    setMessage('');
    setDetail('');
    setRange(next);
  }

  const modelLines = useMemo(() => {
    if (!data) return [];
    return data.series.map((entry, index) => ({ key: entry.key, color: colorFor(index), values: entry.genPoints }));
  }, [data]);

  if (loading && !data) return <p className={styles.muted}>Loading analytics…</p>;
  if (message && !data) return <p className={styles.muted} role="status">{message}{detail ? ` ${detail}` : ''}</p>;
  if (!data) return null;
  if (data.totals.generations === 0) {
    return <p className={styles.muted}>No usage in this range yet. Analytics appear after your first model-powered lesson.</p>;
  }

  const genLines = modelLines.slice(0, 6);
  const inOutLines = [
    { key: 'Input', color: '#2f6fed', values: data.days.map(day => day.promptTokens) },
    { key: 'Output', color: '#e08a3c', values: data.days.map(day => day.completionTokens) },
  ];
  const showCost = data.totals.costIsExact && data.days.some(day => day.cost > 0);

  return (
    <div className={styles.analytics}>
      <section aria-label="Usage history">
        <div className={styles.sectionHead}>
          <div>
            <h2 className={styles.sectionTitle}>Usage history</h2>
            <p className={styles.muted}>See how tokens were consumed across Ask and Learn generations.</p>
          </div>
          <div className={styles.controls}>
            <div role="group" aria-label="Analytics time range" className={styles.rangeRow}>
              {(['7d', '30d'] as const).map(item => (
                <button
                  key={item}
                  type="button"
                  aria-pressed={range === item}
                  className={styles.rangeButton + (range === item ? ` ${styles.rangeActive}` : '')}
                  onClick={() => selectRange(item)}
                >
                  {item}
                </button>
              ))}
            </div>
            <label className={styles.selectLabel}>
              <span className={styles.visuallyHidden}>Group usage history</span>
              <select
                value={dimension}
                onChange={event => { setLoading(true); setMessage(''); setDetail(''); setDimension(event.target.value as AnalyticsDimension); }}
                className={styles.select}
              >
                {DIMENSIONS.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
              </select>
            </label>
          </div>
        </div>
        <HistoryChart data={data} dimension={dimension} />
      </section>

      <section aria-label="Top sessions">
        <h2 className={styles.sectionTitle}>Top sessions</h2>
        <p className={styles.muted}>Compare each session&apos;s token usage. Select a session for its model mix.</p>
        <TopSessions data={data} />
      </section>

      <section aria-label="Generations">
        <div className={styles.sectionHead}>
          <div>
            <h2 className={styles.sectionTitle}>Generations</h2>
            <p className={styles.muted}>Track the number of generations over time.</p>
          </div>
        </div>
        <TrendChart days={data.days.map(day => day.date)} lines={genLines} formatValue={value => `${formatFullTokens(value)}`} />
      </section>

      <section aria-label="Tokens in versus out">
        <h2 className={styles.sectionTitle}>Input vs output</h2>
        <p className={styles.muted}>Prompt tokens entering the model against completion tokens coming back.</p>
        <TrendChart days={data.days.map(day => day.date)} lines={inOutLines} formatValue={value => `${formatCompactTokens(value)} tokens`} />
      </section>

      {showCost ? (
        <section aria-label="Cost over time">
          <h2 className={styles.sectionTitle}>Cost</h2>
          <p className={styles.muted}>Actual provider-reported cost per day.</p>
          <TrendChart
            days={data.days.map(day => day.date)}
            lines={[{ key: 'Cost', color: '#5da271', values: data.days.map(day => Math.round(day.cost * 10000) / 10000) }]}
            formatValue={value => formatCost(value)}
          />
        </section>
      ) : null}
    </div>
  );
}
