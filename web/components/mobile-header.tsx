"use client";
import type { ReactNode } from 'react';
import { AccountMenuActions } from './account-access';
import { Menu, Plus, MessageCircle, BookOpen, FileText, LayoutDashboard, RotateCcw, Settings, Bell, CalendarDays } from 'lucide-react';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from './ui/dropdown-menu';

export function MobileHeader({ title, onNavigate, onNewChat, buddyPicker, history }: {buddyPicker?:ReactNode;history?:ReactNode;title:string;onNavigate:(destination:string)=>void;onNewChat:()=>void}) {
  return <div className="mobile-chat-header"><DropdownMenu><DropdownMenuTrigger asChild><button type="button" aria-label="Open navigation menu"><Menu size={21}/></button></DropdownMenuTrigger><DropdownMenuContent align="start" className="w-56">
    {[['home','Buddy',MessageCircle],['courses','Courses',BookOpen],['calendar','Calendar',CalendarDays],['notes','Notes',FileText],['dashboard','Dashboard',LayoutDashboard],['review','Review',RotateCcw],['reminders','Reminders',Bell],['settings','Settings',Settings]].map(([destination,label,Icon]) => { const ItemIcon=Icon as typeof Menu; return <DropdownMenuItem key={destination as string} onSelect={()=>onNavigate(destination as string)}><ItemIcon size={17}/>{label as string}</DropdownMenuItem>; })}

  <AccountMenuActions/></DropdownMenuContent></DropdownMenu><div className="mobile-header-title">{buddyPicker}<strong title={title}>{title}</strong></div>{history}<button type="button" aria-label="New conversation" onClick={onNewChat}><Plus size={21}/></button></div>;
}
