'use client';

import {useState} from 'react';
import {request} from '@/lib/api';

export type ResearchSource = {
  id: string;
  title: string;
  canonicalUrl?: string | null;
  retrievedAt?: string;
  contentAvailable?: boolean;
};

type SourceDetail = ResearchSource & {excerpt: string; trustLabel: string; semanticSupport: string};

function externalUrl(value?: string | null) {
  try {
    const url = new URL(value || '');
    return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : undefined;
  } catch {
    return undefined;
  }
}

function SourceItem({source}: {source: ResearchSource}) {
  const [detail, setDetail] = useState<SourceDetail | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const href = externalUrl(source.canonicalUrl);

  async function inspect() {
    if (loading) return;
    setLoading(true);
    setError('');
    try {
      const value = await request<SourceDetail>(`/v1/assistant/sources/${encodeURIComponent(source.id)}`);
      setDetail(value);
    } catch (cause) {
      setDetail(null);
      setError(cause instanceof Error ? cause.message : 'This source is unavailable.');
    } finally {
      setLoading(false);
    }
  }

  return <li>
    {href ? <a href={href} target="_blank" rel="noreferrer">{source.title}</a> : <span>{source.title}</span>}
    {' '}<button type="button" disabled={loading} onClick={() => void inspect()} aria-label={`Inspect source: ${source.title}`}>
      {loading ? 'Loading source…' : 'Inspect retained excerpt'}
    </button>
    {detail ? <div>
      <p>Retrieved {detail.retrievedAt}. Source content is evidence to review; its claims are not independently verified.</p>
      <blockquote style={{whiteSpace: 'pre-wrap'}}>{detail.excerpt}</blockquote>
      <button type="button" onClick={() => setDetail(null)}>Close excerpt</button>
    </div> : null}
    {source.contentAvailable === false ? <p>Retained content is unavailable. You can still visit the original source.</p> : null}
    {error ? <p role="alert">{error}</p> : null}
  </li>;
}

export function ResearchSourceList({sources}: {sources: ResearchSource[]}) {
  if (!sources.length) return null;
  return <ul aria-label="Research sources">{sources.map(source => <SourceItem key={source.id} source={source}/>)}</ul>;
}
