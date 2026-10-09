'use client';

import {useId, useRef, useState} from 'react';
import {ChevronDown, Globe2, X} from 'lucide-react';
import {BrowserTaskCard} from './browser-task-card';
import {browserReplyTargets, finishedTask, type BrowserReplyTarget, type BrowserTask} from '@/lib/browser-assistant';
import {browserTaskCopy} from '@/lib/generation-activity';
import styles from './browser-assistant.module.css';

type BrowserTaskCommand = (task: BrowserTask, action: 'pause'|'cancel'|'resume'|'resolve', connectionId?: string, answer?: string, courseId?: string) => Promise<void>;

function taskStatus(task: BrowserTask): string {
  if (task.browserControl?.owner === 'requesting') return 'Handing over browser';
  if (task.browserControl?.owner === 'returning') return 'Returning browser';
  if (task.browserControl?.owner === 'human') return 'Your turn in the browser';
  if (task.status === 'waiting_for_user') return 'Needs your input';
  if (task.status === 'waiting_for_device') return 'Waiting for your browser';
  if (task.status === 'waiting_for_login') return 'Sign in to continue';
  if (task.status === 'paused') return 'Paused';
  if (task.status === 'queued') return 'Starting';
  if (task.status === 'running') return 'Working';
  if (task.status === 'completed_partial') return 'Completed with gaps';
  if (task.status === 'completed') return 'Completed';
  if (task.status === 'cancelled') return 'Stopped';
  if (task.status === 'failed') return 'Could not finish';
  return task.status.replaceAll('_', ' ');
}

function taskTone(task: BrowserTask): 'attention'|'working'|'done'|'error' {
  if (task.status === 'failed') return 'error';
  if (finishedTask(task.status)) return 'done';
  if (task.status.startsWith('waiting') || task.status === 'paused' || task.browserControl?.owner === 'human') return 'attention';
  return 'working';
}

function taskDetail(task: BrowserTask): string {
  if (task.status.startsWith('waiting')) return task.question || 'Open the task to continue.';
  if (task.status === 'paused') return 'Resume this task when you are ready.';
  if (finishedTask(task.status)) return '';
  return browserTaskCopy(task);
}

export function BrowserTaskDock({tasks, onCommand, notice, error, replyTarget, replyTargets, onReplyTargetChange}: {
  tasks: BrowserTask[];
  onCommand: BrowserTaskCommand;
  notice?: string;
  error?: string;
  replyTarget?: BrowserReplyTarget|null;
  replyTargets?: BrowserReplyTarget[];
  onReplyTargetChange?:(target:BrowserReplyTarget|null)=>void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [choosingReply, setChoosingReply] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const currentTask = [...tasks].reverse().find(task => !finishedTask(task.status)) || tasks.at(-1);
  if (!currentTask && !notice && !error) return null;

  const title = error || (currentTask
    ? finishedTask(currentTask.status) && currentTask.summary
      ? currentTask.summary
      : currentTask.message
    : notice || 'Browser update');
  const status = error ? 'Needs attention' : currentTask ? taskStatus(currentTask) : 'Update';
  const tone = error ? 'error' : currentTask ? taskTone(currentTask) : 'attention';
  const toneClass = tone === 'attention' ? styles.attention : tone === 'working' ? styles.working : tone === 'done' ? styles.done : styles.failed;
  const activeTasks = tasks.filter(task => !finishedTask(task.status));
  const recentCompleted = tasks.filter(task => finishedTask(task.status)).slice(-2);
  const availableReplies = replyTargets || browserReplyTargets(tasks);
  const visibleTasks = [...activeTasks, ...recentCompleted]
    .sort((left, right) => left.createdAt - right.createdAt)
    .reverse();

  function close() {
    setExpanded(false);
    trigger.current?.focus();
  }

  return <section className={styles.dock} aria-label="Browser activity" onKeyDown={event => { if (event.key === 'Escape' && expanded) { event.stopPropagation(); close(); } }}>
    {availableReplies.length || replyTarget ? <div className={styles.replyTarget} role="group" aria-label="Browser reply target">
      {replyTarget ? <>
        <span className={styles.replyTargetLabel}>Replying to Buddy</span>
        <span className={styles.replyTargetQuestion}>{replyTarget.question}</span>
        {availableReplies.length>1?<button type="button" onClick={()=>setChoosingReply(value=>!value)} aria-expanded={choosingReply}>Switch</button>:null}
        <button type="button" onClick={()=>{onReplyTargetChange?.(null);setChoosingReply(false);}}>New message</button>
      </> : <>
        <span className={styles.replyTargetLabel}>Choose which browser question to answer</span>
        {availableReplies.length===1?<button type="button" onClick={()=>onReplyTargetChange?.(availableReplies[0])}>Reply to question</button>:null}
      </>}
      {choosingReply || (!replyTarget && availableReplies.length>1) ? <div className={styles.replyOptions}>
        {availableReplies.map(target=><button key={target.replyToRequestId} type="button" onClick={()=>{onReplyTargetChange?.(target);setChoosingReply(false);}}>
          <span>{target.question}</span><small>Task {target.targetTaskId.slice(0,8)}</small>
        </button>)}
      </div>:null}
    </div>:null}
    <button
      ref={trigger}
      type="button"
      className={styles.dockTrigger}
      aria-expanded={expanded}
      aria-controls={expanded ? panelId : undefined}
      onClick={() => setExpanded(value => !value)}
    >
      <span className={styles.dockIcon} aria-hidden="true"><Globe2 size={18}/></span>
      <span className={styles.dockCopy}>
        <span className={styles.dockLabel}>Browser task</span>
        <strong className={styles.dockTitle}>{title}</strong>
        <span className={styles.dockMeta} role="status" aria-live="polite"><span className={`${styles.statusDot} ${toneClass}`} aria-hidden="true"/>{status}{!error && currentTask && taskDetail(currentTask) ? ` · ${taskDetail(currentTask)}` : ''}</span>
      </span>
      <span className={styles.dockAction}>{expanded ? 'Hide' : 'Review'}<ChevronDown size={15} className={expanded ? styles.chevronOpen : ''}/></span>
    </button>
    {expanded ? <div id={panelId} className={styles.dockTray} role="region" aria-label="Browser task details">
      <div className={styles.dockTrayHeader}>
        <div><strong>Browser activity</strong><span>{activeTasks.length ? `${activeTasks.length} task${activeTasks.length === 1 ? '' : 's'} need attention or are in progress` : 'Recent browser task'}</span></div>
        <button type="button" aria-label="Close browser activity" onClick={close}><X size={17}/></button>
      </div>
      {error ? <p className={styles.dockError} role="alert">{error}</p> : null}
      {notice ? <p className={styles.dockNotice} role="status">{notice}</p> : null}
      <div className={styles.dockTaskList}>
        {visibleTasks.map(task => <BrowserTaskCard key={task.id} task={task} onCommand={onCommand}/>) }
      </div>
    </div> : null}
  </section>;
}
