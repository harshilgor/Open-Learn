'use client';
import { useId, useState } from 'react';
import { CalendarPlus } from 'lucide-react';
import { parseQuickAdd, type QuickAddDraft } from '@/lib/calendar-quick-add';
import styles from './calendar.module.css';

/** Header input that turns "Bio study tomorrow 3pm" into a prefilled event form for the user to confirm. */
export function CalendarQuickAdd({ today, onDraft }: { today: string; onDraft: (draft: QuickAddDraft) => void }) {
  const [text, setText] = useState('');
  const hint = useId();
  return <form className={styles.quickAdd} onSubmit={event => {
    event.preventDefault();
    if (!text.trim()) return;
    onDraft(parseQuickAdd(text, today));
    setText('');
  }}>
    <CalendarPlus size={15} aria-hidden="true"/>
    <input type="text" value={text} onChange={event => setText(event.target.value)} aria-label="Quick add event" aria-describedby={hint} placeholder="Add event… e.g. ‘Bio study tomorrow 3pm’" enterKeyHint="done" autoComplete="off" spellCheck={false} maxLength={300}/>
    <span id={hint} className="sr-only">Type a title with a day and time, such as Chem exam Oct 20 9 to 11am, then press Enter to review it before saving.</span>
  </form>;
}
