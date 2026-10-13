"use client";

import { useState } from 'react';
import { Bell, CalendarDays, BookOpen, ChevronDown, FileText, History, Home, Plus, RotateCcw, Search, Settings } from 'lucide-react';
import { BuddyAvatar, useBuddies } from './buddies';
import { ChatHistory } from './chat-history';
import { AccountMenuActions, AccountProfile } from './account-access';
import { Popover, PopoverContent, PopoverTrigger } from './ui/popover';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from './ui/dropdown-menu';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from './ui/sheet';
import type { CourseSummary } from '@/lib/api';
import './workspace-rail.css';

type Props = {
  activeSessionId: string | null; refreshKey: number; courses: CourseSummary[];
  onSwitch: (id: string) => void; onOpen: (id: string | null) => void;
  onNavigate: (destination: string) => void;
};

export function WorkspaceRail(props: Props) {
  const { snapshot, active, edit, error, refresh } = useBuddies();
  const [flyout, setFlyout] = useState<string | null>(null);
  const history = (buddyId?: string) => <ChatHistory activeSessionId={props.activeSessionId} refreshKey={props.refreshKey} courses={props.courses} fixedBuddyId={buddyId} onOpen={id => { props.onOpen(id); setFlyout(null); }} />;
  return <nav className="workspace-rail" aria-label="Main navigation">
    <button title="Home" aria-label="Home" onClick={() => props.onNavigate('dashboard')}><Home size={21}/></button>
    <Popover open={flyout === 'search'} onOpenChange={open => setFlyout(open ? 'search' : null)}><PopoverTrigger asChild><button title="Search all chats" aria-label="Search all chats"><Search size={21}/></button></PopoverTrigger><PopoverContent side="right" align="start" sideOffset={14} className="chat-history-flyout" aria-label="Search all chats"><h2>All conversations</h2>{history()}</PopoverContent></Popover>
    <button title="Courses" aria-label="Courses" onClick={() => props.onNavigate('courses')}><BookOpen size={21}/></button>
    <button title="Calendar" aria-label="Calendar" onClick={() => props.onNavigate('calendar')}><CalendarDays size={21}/></button>
    <div className="rail-buddies">
      {snapshot?.profiles.filter(buddy => !buddy.archived).map(buddy => {
        const count = Object.values(snapshot.chats).filter(id => id === buddy.id).length;
        return <div className="rail-buddy" key={buddy.id}>
          <button title={buddy.name} aria-label={`Open ${buddy.name}`} aria-pressed={active?.id === buddy.id} onClick={() => { setFlyout(null); props.onSwitch(buddy.id); }}><BuddyAvatar buddy={buddy}/>{snapshot.unread?.[buddy.id] ? <span className="rail-unread" aria-label={`${snapshot.unread[buddy.id]} unread reminders`}/> : null}</button>
          {count > 1 && active?.id === buddy.id ? <Popover open={flyout === buddy.id} onOpenChange={open => setFlyout(open ? buddy.id : null)}><PopoverTrigger asChild><button className="rail-history-toggle" title={`${buddy.name} chats`} aria-label={`Show chats with ${buddy.name}`}><ChevronDown size={13}/></button></PopoverTrigger><PopoverContent side="right" align="start" sideOffset={12} className="chat-history-flyout" aria-label={`${buddy.name} conversations`}><div className="history-heading"><h2>{buddy.name} chats</h2><button title="New chat" aria-label={`New chat with ${buddy.name}`} onClick={() => { props.onOpen(null); setFlyout(null); }}><Plus size={18}/></button></div>{history(buddy.id)}</PopoverContent></Popover> : null}
        </div>;
      })}
      <button title="Add buddy" aria-label="Add buddy" onClick={() => edit()}><Plus size={21}/></button>
      {error ? <button title={error} aria-label="Retry loading buddies" onClick={() => void refresh()}><RotateCcw size={18}/></button> : null}
    </div>
    <DropdownMenu><DropdownMenuTrigger asChild><button className="rail-account" title="Account and navigation" aria-label="Account menu"><AccountProfile/></button></DropdownMenuTrigger><DropdownMenuContent side="right" align="end" sideOffset={12} className="min-w-52">
      <DropdownMenuItem onSelect={() => props.onNavigate('notes')}><FileText size={17}/>Notes</DropdownMenuItem>
      <DropdownMenuItem onSelect={() => props.onNavigate('review')}><RotateCcw size={17}/>Review</DropdownMenuItem>
      <DropdownMenuItem onSelect={() => props.onNavigate('reminders')}><Bell size={17}/>Reminders</DropdownMenuItem>
      <DropdownMenuItem onSelect={() => props.onNavigate('settings')}><Settings size={17}/>Settings</DropdownMenuItem>
      <AccountMenuActions/>
    </DropdownMenuContent></DropdownMenu>
  </nav>;
}

export function MobileChatHistory(props: Pick<Props, 'activeSessionId' | 'refreshKey' | 'courses' | 'onOpen'>) {
  const { active } = useBuddies();
  const [open, setOpen] = useState(false);
  const [all, setAll] = useState(false);
  return <><button className="mobile-history-trigger" title="Chat history" aria-label="Open chat history" onClick={() => setOpen(true)}><History size={20}/></button><Sheet open={open} onOpenChange={setOpen}><SheetContent side="bottom" className="mobile-history-sheet"><SheetHeader><SheetTitle>{all ? 'All conversations' : `${active?.name || 'Buddy'} chats`}</SheetTitle><SheetDescription>Pick up where you left off.</SheetDescription></SheetHeader><div className="mobile-history-body"><button className="history-scope" onClick={() => setAll(value => !value)}>{all ? 'Show this buddy only' : 'Search across all buddies'}</button><ChatHistory fixedBuddyId={all ? undefined : active?.id} {...props} onOpen={id => { props.onOpen(id); setOpen(false); }}/></div></SheetContent></Sheet></>;
}
