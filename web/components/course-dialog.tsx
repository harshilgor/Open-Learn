'use client';

import { useState, type FormEvent } from 'react';
import { FolderClosed, Loader2 } from 'lucide-react';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { learningApi, LearningApiError, type CoursePublic } from '@/lib/api';

interface CourseDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (course: CoursePublic) => void;
}

export function CourseDialog({ open, onOpenChange, onCreated }: CourseDialogProps) {
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function createCourse(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    setError('');
    try {
      const course = await learningApi.createCourse({ name: trimmed });
      setName('');
      onOpenChange(false);
      onCreated(course);
    } catch (cause) {
      setError(cause instanceof LearningApiError && cause.status === 404
        ? 'The local tutor service is out of date. Restart it, then try again.'
        : cause instanceof Error ? cause.message : 'Could not create this course.');
    } finally {
      setBusy(false);
    }
  }

  return <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent className="sm:max-w-[420px]">
      <form onSubmit={createCourse} className="space-y-5">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-lg"><FolderClosed size={20} />New course</DialogTitle>
          <DialogDescription>Keep related chats, notes, and quizzes together.</DialogDescription>
        </DialogHeader>
        {error ? <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p> : null}
        <div className="space-y-2">
          <label htmlFor="course-name" className="text-sm font-medium">Course name</label>
          <input id="course-name" autoFocus required maxLength={300} value={name} onChange={event => setName(event.target.value)} placeholder="e.g. Physics" className="h-10 w-full rounded-lg border border-input bg-background px-3 text-sm text-foreground" />
        </div>
        <DialogFooter>
          <Button type="button" variant="ghost" disabled={busy} onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button type="submit" disabled={!name.trim() || busy}>{busy ? <><Loader2 size={16} className="animate-spin" />Creating…</> : 'Create course'}</Button>
        </DialogFooter>
      </form>
    </DialogContent>
  </Dialog>;
}
