"use client";

import { useState } from 'react';
import { ArrowUpRight, BookOpenCheck } from 'lucide-react';
import { learningApi } from '@/lib/api';
import { openChatSession } from '@/lib/workspace-events';
import styles from './study-note-panel.module.css';

type Mode = 'ask' | 'auto' | 'never';

/**
 * Study-note provenance bar: which chat maintains this note, how the tutor
 * may update it, and a way back to "how I learned this".
 */
export function StudyNoteBar({ draft, onChanged }: {
  draft: { id: string | null; revision: number | null; frontmatter: Record<string, unknown> } | null;
  onChanged: (revision: number, frontmatter: Record<string, unknown>) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  if (!draft?.id || draft.frontmatter?.study_note !== true) return null;
  const sessions = Array.isArray(draft.frontmatter.session_ids) ? draft.frontmatter.session_ids as string[] : [];
  const mode = (draft.frontmatter.tutor_updates === 'auto' || draft.frontmatter.tutor_updates === 'never')
    ? draft.frontmatter.tutor_updates as Mode
    : 'ask';

  async function changeMode(next: Mode) {
    if (!draft?.id || !draft.revision || busy || next === mode) return;
    setBusy(true); setError('');
    try {
      const result = await learningApi.setStudyNoteMode(draft.id, next, draft.revision);
      onChanged(result.revision, { ...draft.frontmatter, tutor_updates: result.tutorUpdates });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The update mode could not be changed.');
    } finally { setBusy(false); }
  }

  return (
    <div className={styles.studyBar} aria-label="Study note provenance">
      <div className={styles.studyBarDetails}>
        <BookOpenCheck size={15} />
        <span className={styles.studyBarText}>
          Study note{mode === 'auto' ? ' · grows automatically as you learn' : mode === 'never' ? ' · tutor never edits' : ' · tutor proposes additions'}
        </span>
        {draft.frontmatter.course_id ? <span className={styles.courseTag} title="Attached to course">Course note</span> : null}
      </div>
      <div className={styles.studyBarActions}>
        {sessions.length > 0 ? (
          <button type="button" className={styles.studyBarLink} onClick={() => openChatSession(sessions[0])}>
            Open chat<ArrowUpRight size={13} />
          </button>
        ) : null}
        <label className={styles.studyBarMode}>
          <span className="sr-only">Tutor updates</span>
          <select value={mode} disabled={busy} aria-label="Tutor updates"
            onChange={event => void changeMode(event.target.value as Mode)}>
            <option value="ask">Ask first</option>
            <option value="auto">Auto-add</option>
            <option value="never">Never</option>
          </select>
        </label>
      </div>
      {error ? <span className={styles.error} role="alert">{error}</span> : null}
    </div>
  );
}
