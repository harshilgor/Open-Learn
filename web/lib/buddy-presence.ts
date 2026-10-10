"use client";
import {useEffect, useState} from 'react';

export function restingExpression(minutes:number, hour:number, away:boolean):'Neutral'|'Sleepy'|'Sleeping' {
  if(away)return 'Sleeping';
  return minutes>=45 || hour>=22 || hour<6 ? 'Sleepy' : 'Neutral';
}

/** Only foreground time with this Buddy counts. Local clock follows the device timezone. */
export function useBuddyPresence(id:string, enabled=true) {
  const [expression,setExpression]=useState<'Neutral'|'Sleepy'|'Sleeping'|'Waking'>('Neutral');
  useEffect(()=>{
    if(!enabled)return;
    const key=`openlearn-buddy-presence:${id}`;
    let minutes=0, last=Date.now(), away=!document.hasFocus() || document.hidden;
    let awaySince=Date.now();
    let wakingUntil=Date.now()+2600;
    try{const saved=JSON.parse(sessionStorage.getItem(key)||'null');if(saved && Date.now()-saved.last<15*60_000)minutes=Math.max(0,Math.min(180,Number(saved.minutes)||0));}catch{/* Optional local animation history. */}
    const update=()=>{
      const now=Date.now();
      if(!away)minutes+=Math.min(now-last,30_000)/60_000;
      last=now;
      setExpression(!away && now<wakingUntil ? 'Waking' : restingExpression(minutes,new Date().getHours(),away));
      try{sessionStorage.setItem(key,JSON.stringify({minutes,last:now}));}catch{/* Animation still works without storage. */}
    };
    const wake=()=>{if(document.hidden)return;if(away){if(Date.now()-awaySince>=15*60_000)minutes=0;wakingUntil=Date.now()+2600;}away=false;update();};
    const rest=()=>{update();awaySince=Date.now();away=true;setExpression('Sleeping');};
    const visibility=()=>{if(document.hidden)rest();else wake();};
    const start=window.setTimeout(update,0),timer=window.setInterval(update,1000);
    window.addEventListener('focus',wake);window.addEventListener('blur',rest);document.addEventListener('visibilitychange',visibility);
    return()=>{clearTimeout(start);clearInterval(timer);window.removeEventListener('focus',wake);window.removeEventListener('blur',rest);document.removeEventListener('visibilitychange',visibility);};
  },[id,enabled]);
  return enabled?expression:'Neutral';
}
