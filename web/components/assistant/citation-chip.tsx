"use client";

import type { ReactNode } from 'react';
import { BookOpen, FileText, Globe } from 'lucide-react';
import { openWorkspaceSource } from '@/lib/workspace-events';
import { citationDescription, citationPage, parseCitationHref, type CitationSource } from '@/lib/answer-reading';
import styles from './answer-reading.module.css';

/**
 * A compact source pill. With a span id it opens the cited passage through the
 * global source-open event (SourcePassageDialog); without one it is a static marker.
 */
export function CitationChip({ source, label, origin = 'material' }: { source: CitationSource; label?: string; origin?: 'web' | 'material' }) {
  const page = citationPage(source);
  const description = citationDescription(source);
  const Icon = origin === 'web' ? Globe : source.pageIndex !== undefined || source.pageLabel ? BookOpen : FileText;
  const title = source.title?.trim();
  const content = <>
    <Icon size={12} strokeWidth={2.2} aria-hidden="true" className={styles.chipIcon} />
    {label ? <span className={styles.chipTitle}>{label}</span> : <>
      {title ? <span className={styles.chipTitle}>{title}</span> : null}
      {page ? <span className={styles.chipPage}>{page}</span> : null}
      {!title && !page ? <span className={styles.chipTitle}>Source</span> : null}
    </>}
  </>;
  if (!source.spanId) {
    return <span className={styles.chip} data-static="true" title={description}>
      <span className="sr-only">Citation: </span>{content}
    </span>;
  }
  const spanId = source.spanId;
  return <button
    type="button"
    className={styles.chip}
    title={description}
    aria-label={`Open cited passage: ${description}`}
    onClick={() => openWorkspaceSource({ spanId, versionId: source.versionId, title })}
  >{content}</button>;
}

/** Inline chip for a `citation:` link produced by encodeCitationMarkers. */
export function InlineCitation({ href, children }: { href: string; children?: ReactNode }) {
  const parsed = parseCitationHref(href);
  if (!parsed) return <>{children}</>;
  if (parsed.kind === 'span') return <CitationChip source={{ spanId: parsed.spanId }} />;
  return <CitationChip
    source={{ title: parsed.origin === 'web' ? `Web source ${parsed.alias}` : `Course material ${parsed.alias}` }}
    label={parsed.alias}
    origin={parsed.origin}
  />;
}

/** A wrapped row of citation chips, e.g. the passages behind a materials answer. */
export function CitationList({ sources, label }: { sources: CitationSource[]; label: string }) {
  if (!sources.length) return null;
  return <ul className={styles.citationList} aria-label={label}>
    {sources.map((source, index) => <li key={source.spanId || `${source.title}-${index}`}><CitationChip source={source} /></li>)}
  </ul>;
}
