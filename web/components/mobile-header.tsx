"use client";
import { Menu, Plus, MessageCircle, BookOpen, FileText, LayoutDashboard, RotateCcw, Settings, History } from 'lucide-react';
import { useSidebar } from './ui/sidebar';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from './ui/dropdown-menu';

export function MobileHeader({ title, onNavigate, onNewChat }: {title:string;onNavigate:(destination:string)=>void;onNewChat:()=>void}) {
  const { setOpenMobile } = useSidebar();
  return <div className="mobile-chat-header"><DropdownMenu><DropdownMenuTrigger asChild><button type="button" aria-label="Open navigation menu"><Menu size={21}/></button></DropdownMenuTrigger><DropdownMenuContent align="start" className="w-56">
    {[['home','Buddy',MessageCircle],['courses','Courses',BookOpen],['notes','Notes',FileText],['dashboard','Dashboard',LayoutDashboard],['review','Review',RotateCcw],['settings','Settings',Settings]].map(([destination,label,Icon]) => { const ItemIcon=Icon as typeof Menu; return <DropdownMenuItem key={destination as string} onSelect={()=>onNavigate(destination as string)}><ItemIcon size={17}/>{label as string}</DropdownMenuItem>; })}
    <DropdownMenuSeparator/><DropdownMenuItem onSelect={()=>setOpenMobile(true)}><History size={17}/>Chats and history</DropdownMenuItem>
  </DropdownMenuContent></DropdownMenu><div className="mobile-header-title"><span>Open Learn</span><strong>{title}</strong></div><button type="button" aria-label="New conversation" onClick={onNewChat}><Plus size={21}/></button></div>;
}
