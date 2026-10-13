"use client";

import { BookOpen, LayoutDashboard, MessageCircle, Menu } from 'lucide-react';
import { useSidebar } from './ui/sidebar';
import './mobile-navigation.css';

export function MobileNavigation({ view, onBuddy, onDashboard, onCourses, conversationOpen = false }: { view: string; onBuddy: () => void; onDashboard: () => void; onCourses?:()=>void; conversationOpen?: boolean }) {
  const { setOpenMobile } = useSidebar();
  return <nav className={`mobile-workspace-nav${conversationOpen ? ' conversation-open' : ''}`} aria-label="Mobile workspace">
    <button type="button" aria-current={view === 'home' ? 'page' : undefined} onClick={onBuddy}><MessageCircle size={20} /><span>Buddy</span></button>
    <button type="button" aria-current={view === 'course'||view==='courses' ? 'page' : undefined} onClick={onCourses||(()=>setOpenMobile(true))}><BookOpen size={20} /><span>Courses</span></button>
    <button type="button" aria-current={view === 'dashboard' ? 'page' : undefined} onClick={onDashboard}><LayoutDashboard size={20} /><span>Dashboard</span></button>
    <button type="button" onClick={() => setOpenMobile(true)}><Menu size={20} /><span>More</span></button>
  </nav>;
}
