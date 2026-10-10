"use client";
import { motion } from 'motion/react';
import type { OutboxMessage } from '@/lib/chat-outbox';
import { useAppReducedMotion } from '@/lib/use-app-reduced-motion';
import styles from './learn-chat.module.css';

export function OutgoingMessages({messages,turns,onRetry,onRemove}:{
  messages:OutboxMessage[];turns:{question:string}[];onRetry:(id:string)=>void;onRemove:(id:string)=>void;
}){
  const reduceMotion=useAppReducedMotion();
  return <div className={styles.outbox} aria-label="Outgoing messages">
    {messages.filter(message=>!(message.status==='accepted'&&turns.slice(message.baseTurn).some(turn=>turn.question===message.text))).map((message,index)=><motion.div key={message.id} className={styles.outgoingMessage} initial={reduceMotion?false:{opacity:0,y:6,scale:.98}} animate={{opacity:1,y:0,scale:1}} transition={{duration:.14}}>
      {message.status==='queued'||!turns.slice(message.baseTurn).some(turn=>turn.question===message.text)?<div className={`${styles.userPrompt} ${index>0?styles.consecutivePrompt:''}`}><p>{message.text}</p></div>:null}
      <div className={styles.deliveryStatus} role="status">{message.status==='sending'?'Sending…':message.status==='accepted'?'Sent · response in progress':message.status==='choice'?'Choose how Buddy should help':message.status==='failed'?message.error:'Waiting for Buddy'}
        {message.status==='failed'?<button type="button" onClick={()=>onRetry(message.id)}>Retry</button>:null}
        {message.status!=='sending'&&message.status!=='accepted'&&message.status!=='choice'?<button type="button" aria-label={`Remove queued message: ${message.text.slice(0,40)}`} onClick={()=>onRemove(message.id)}>Remove</button>:null}
      </div>
    </motion.div>)}
  </div>;
}
