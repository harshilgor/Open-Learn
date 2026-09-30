"use client";
import { useState } from 'react';
import { motion } from 'motion/react';
import { useAppReducedMotion } from '@/lib/use-app-reduced-motion';
import { FileText, Trash2, Save, ExternalLink } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { learningApi, type NoteDraft } from '@/lib/api';
import { openWorkspaceNoteDraft, openWorkspaceNote } from '@/lib/workspace-events';
import styles from './learn-chat.module.css';
export function NoteDraftCard({ draft, onHandled }: { draft: NoteDraft; onHandled: (draft: NoteDraft) => void }) {
 const reduceMotion=useAppReducedMotion();
 const [busy,setBusy]=useState(false); const [error,setError]=useState('');
 async function save(){setBusy(true);setError('');try{const result=await learningApi.saveNoteDraft(draft.id);onHandled({...draft,status:'saved'});openWorkspaceNote(result.noteId)}catch(e){setError(e instanceof Error?e.message:'Could not save note draft.')}finally{setBusy(false)}}
 async function discard(){setBusy(true);setError('');try{await learningApi.discardNoteDraft(draft.id);onHandled({...draft,status:'discarded'})}catch(e){setError(e instanceof Error?e.message:'Could not discard note draft.')}finally{setBusy(false)}}
 function open(){openWorkspaceNoteDraft({title:draft.title,body:draft.body,frontmatter:{generated:true,generated_label:draft.generatedLabel,draft_id:draft.id,source_anchors:draft.sourceAnchors,tags:draft.proposedTags}})}
 if(draft.status!=='ready') return null;
 return <motion.section className={styles.noteDraft} aria-label="AI note draft" initial={reduceMotion?false:{opacity:0,y:10}} animate={{opacity:1,y:0}} transition={{duration:.18,ease:'easeOut'}}><header><FileText size={16}/><strong>AI note draft</strong><span>Editable before saving</span></header><h3>{draft.title}</h3><pre>{draft.body}</pre>{draft.proposedTags.length?<p>Tags: {draft.proposedTags.map(x=>`#${x}`).join(' ')}</p>:null}<p className={styles.noteDraftSources}>From: {draft.sourceAnchors.map(source=>source.label).join(', ')}</p><div className={styles.lessonActions}><Button size="sm" variant="outline" disabled={busy} onClick={open}><ExternalLink size={14}/>Open in Notes</Button><Button size="sm" disabled={busy} onClick={()=>void save()}><Save size={14}/>Save as new note</Button>{draft.replacement?<Button size="sm" disabled={busy} onClick={async()=>{setBusy(true);try{await learningApi.replaceNoteDraft(draft.id,{expectedNoteRevision:draft.replacement!.expectedRevision,startOffset:draft.replacement!.startOffset,endOffset:draft.replacement!.endOffset});onHandled({...draft,status:'replaced'});openWorkspaceNote(draft.replacement!.noteId)}catch(e){setError(e instanceof Error?e.message:'Could not replace note section.')}finally{setBusy(false)}}}>Replace selected section</Button>:null}<Button size="sm" variant="ghost" disabled={busy} onClick={()=>void discard()}><Trash2 size={14}/>Discard</Button></div>{error?<p className={styles.error} role="alert">{error}</p>:null}</motion.section>
}
