"use client";

import type { CSSProperties, ReactNode } from 'react';
import { ArrowUpRight, FolderClosed, FolderPlus, Plus, LayoutDashboard, SquarePen } from 'lucide-react';
import { Button } from './ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from './ui/dropdown-menu';
import { ChatHistory } from './chat-history';
import type { CourseSummary } from '@/lib/api';

export type WorkspaceSidebarTab = 'home' | 'notes';
export type NotesCommand = { id: number; action: 'new-note' | 'new-folder' };

export function SidebarTabs({ tab, onChange }: { tab: WorkspaceSidebarTab; onChange: (tab: WorkspaceSidebarTab) => void }) {
  return <div className="sidebar-tabs" role="tablist" aria-label="Workspace sections">
    {(['home', 'notes'] as const).map(value => <button key={value} id={`sidebar-tab-${value}`} role="tab" type="button" aria-selected={tab === value} aria-controls={`sidebar-body-${value}`} tabIndex={tab === value ? 0 : -1} onClick={() => onChange(value)} onKeyDown={event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 'home' : event.key === 'End' ? 'notes' : value === 'home' ? 'notes' : 'home';
      onChange(next);
      document.getElementById(`sidebar-tab-${next}`)?.focus();
    }}>{value === 'home' ? 'Home' : 'Notes'}</button>)}
  </div>;
}

export function WorkspaceSidebar({ tab, onTabChange, collapseControl, courses, activeCourseId, onCourseSelect, onCourseOpen, onNewChat, onNewCourse, onNotesCommand, onDashboard, dashboardActive, activeSessionId, refreshKey, onOpenSession, notesHost }: {
  tab: WorkspaceSidebarTab; onTabChange: (tab: WorkspaceSidebarTab) => void; collapseControl: ReactNode;
  courses: CourseSummary[]; activeCourseId: string | null; onCourseSelect: (id: string | null) => void; onCourseOpen: (id: string) => void;
  onNewChat: () => void; onNewCourse: () => void; onNotesCommand: (action: NotesCommand['action']) => void;
  dashboardActive?: boolean; onReminders?:()=>void; onDashboard: () => void; activeSessionId: string | null; refreshKey: number;
  onOpenSession: (id: string | null) => void; notesHost: (node: HTMLDivElement | null) => void;
}) {
  return <>
    <div className="brand">Open Learn{collapseControl}</div>
    <SidebarTabs tab={tab} onChange={onTabChange} />
    <DropdownMenu><DropdownMenuTrigger asChild><Button className="sidebar-new" aria-label="Create new"><Plus size={18} />New</Button></DropdownMenuTrigger><DropdownMenuContent align="start">
      {tab === 'home' ? <><DropdownMenuItem onSelect={onNewChat}><SquarePen size={16} />New chat</DropdownMenuItem><DropdownMenuItem onSelect={onNewCourse}><FolderPlus size={16} />New course</DropdownMenuItem></> : <><DropdownMenuItem onSelect={() => onNotesCommand('new-note')}><SquarePen size={16} />New note</DropdownMenuItem><DropdownMenuItem onSelect={() => onNotesCommand('new-folder')}><FolderPlus size={16} />New folder</DropdownMenuItem></>}
    </DropdownMenuContent></DropdownMenu>
    <button type="button" className={`nav-item${dashboardActive ? ' active' : ''}`} aria-current={dashboardActive ? 'page' : undefined} onClick={onDashboard}><LayoutDashboard size={17} />Dashboard</button>
    <div className="side-label">Courses</div>
    <div className="courses-list" aria-label="Course filters">
      <button type="button" className={`course-link ${activeCourseId === null ? 'active' : ''}`} aria-pressed={activeCourseId === null} onClick={() => onCourseSelect(null)}><FolderClosed size={16} /><span>All courses</span></button>
      {courses.map(course => <div className="sidebar-course-row" key={course.id}>
        <button type="button" className={`course-link ${activeCourseId === course.id ? 'active' : ''}`} aria-pressed={activeCourseId === course.id} onClick={() => onCourseSelect(course.id)} title={course.name}><FolderClosed size={16} /><span className="truncate">{course.name}</span>{course.roadmapProgress > 0 ? <span className="course-progress" role="img" aria-label={`${Math.round(course.roadmapProgress)}% course progress`} style={{ '--progress': `${Math.min(100, course.roadmapProgress)}%` } as CSSProperties} /> : null}</button>
        <button type="button" className="sidebar-course-open" aria-label={`Open ${course.name} course`} title="Open course" onClick={() => onCourseOpen(course.id)}><ArrowUpRight size={14} /></button>
      </div>)}
    </div>
    <div id="sidebar-body-home" role="tabpanel" aria-labelledby="sidebar-tab-home" hidden={tab !== 'home'}>
      <ChatHistory activeSessionId={activeSessionId} refreshKey={refreshKey} onOpen={onOpenSession} courses={courses} courseFilter={activeCourseId} />
    </div>
    <div id="sidebar-body-notes" role="tabpanel" aria-labelledby="sidebar-tab-notes" hidden={tab !== 'notes'} ref={notesHost} />
  </>;
}
