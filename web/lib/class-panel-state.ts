"use client";
import {useEffect,useState} from 'react';

// Store only layout choices; note text and Buddy drafts stay in their components.
export function useClassPanelState(classId:string,panel:string){
  const [choice,setChoice]=useState<{scope:string;open:boolean}>({scope:'',open:true});
  const key=`openlearn.class-panels.v1:${classId}:${panel}`;
  useEffect(()=>{let open=true;try{open=sessionStorage.getItem(key)!=='closed';}catch{}setChoice({scope:key,open});},[key]);
  const open=choice.scope===key?choice.open:true;
  return [open,(value:boolean)=>{setChoice({scope:key,open:value});try{sessionStorage.setItem(key,value?'open':'closed');}catch{}}] as const;
}
