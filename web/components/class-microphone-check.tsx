"use client";
import {useEffect,useRef,useState} from 'react';
import {Button} from './ui/button';

export function ClassMicrophoneCheck({microphoneId}:{microphoneId:string}){
  const [running,setRunning]=useState(false),[level,setLevel]=useState(0),[message,setMessage]=useState('');
  const cleanup=useRef<(()=>void)|null>(null),generation=useRef(0);
  useEffect(()=>{setRunning(false);setLevel(0);return()=>{generation.current++;cleanup.current?.();};},[microphoneId]);
  async function check(){
    const attempt=++generation.current;cleanup.current?.();setRunning(true);setMessage('Speak normally for five seconds. This check stays on your device.');
    try{
      const stream=await navigator.mediaDevices.getUserMedia({audio:microphoneId?{deviceId:{exact:microphoneId}}:true});
      if(attempt!==generation.current){stream.getTracks().forEach(track=>track.stop());return;}
      cleanup.current=()=>stream.getTracks().forEach(track=>track.stop());
      const context=new AudioContext(),source=context.createMediaStreamSource(stream),analyser=context.createAnalyser();
      analyser.fftSize=1024;source.connect(analyser);
      const samples=new Float32Array(analyser.fftSize);let peak=0,clipped=0;
      const finish=()=>{clearInterval(timer);clearTimeout(end);source.disconnect();stream.getTracks().forEach(track=>track.stop());void context.close();};
      const timer=setInterval(()=>{analyser.getFloatTimeDomainData(samples);const rms=Math.sqrt(samples.reduce((sum,value)=>sum+value*value,0)/samples.length);peak=Math.max(peak,rms);if(samples.some(value=>Math.abs(value)>.98))clipped++;setLevel(Math.min(1,rms*8));},100);
      const end=setTimeout(()=>{finish();cleanup.current=null;setRunning(false);setMessage(clipped>3?'Input is clipping. Move farther from the microphone.':peak<.008?'Very little input detected. Check the selected microphone and move closer.':'Input detected. Place the microphone near the speaker. This does not measure transcription accuracy.');},5000);
      cleanup.current=finish;await context.resume();
    }catch(cause){cleanup.current?.();cleanup.current=null;if(attempt===generation.current){setRunning(false);setMessage(cause instanceof Error?cause.message:'Microphone check unavailable.');}}
  }
  return <section aria-label="Microphone input check"><Button type="button" variant="outline" disabled={running} onClick={()=>void check()}>Check microphone input</Button>{running?<meter aria-label="Microphone level" min={0} max={1} value={level}/>:null}<p role="status">{message||'Check input before starting. No audio is uploaded or saved.'}</p></section>;
}
