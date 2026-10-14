import {AppState} from 'react-native';
import * as Crypto from 'expo-crypto';
import Capture from './modules-placeholder';
import {api,account} from './account';
import {captureCredential} from './recordings';
import type {Recording} from './protocol';

function decode(value:string){
  const alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  const bytes:number[]=[];let bits=0,held=0;
  for(const character of value){if(character==='=')break;const digit=alphabet.indexOf(character);if(digit<0)continue;held=(held<<6)|digit;bits+=6;if(bits>=8){bits-=8;bytes.push((held>>bits)&255);}}
  return new Uint8Array(bytes);
}

export function startPhoneCaptions(getRecord:()=>Recording,onStatus:(value:string)=>void){
  const record=getRecord();
  if(typeof Capture.setLivePcmEnabled!=='function'){
    onStatus('Rebuild the phone app to enable live captions. Recorded audio remains available.');return()=>{};
  }
  let stopped=false,socket:WebSocket|null=null,timer:ReturnType<typeof setTimeout>|null=null,retries=0;
  let phase=0,sum=0,count=0,position=0,frame=new Int16Array(1600);
  const subscription=Capture.addListener('pcm',event=>{
    void Capture.ackPcm().catch(()=>undefined);
    if(stopped||event.recordingId!==record.id||account()?.owner!==record.owner||socket?.readyState!==WebSocket.OPEN)return;
    if(event.sampleRate<16000||event.sampleRate>48000||event.data.length>16000)return;
    const data=decode(event.data),view=new DataView(data.buffer);
    for(let offset=0;offset+1<data.length;offset+=2){
      sum+=view.getInt16(offset,true);count++;phase+=16000;
      if(phase>=event.sampleRate){phase-=event.sampleRate;frame[position++]=Math.round(sum/count);sum=0;count=0;
        if(position===frame.length){if(socket&&socket.readyState===WebSocket.OPEN&&socket.bufferedAmount<64000)socket.send(frame.buffer);frame=new Int16Array(1600);position=0;}
      }
    }
  });
  async function connect(){
    if(stopped||AppState.currentState!=='active'||account()?.owner!==record.owner)return;
    if(socket&&(socket.readyState===WebSocket.OPEN||socket.readyState===WebSocket.CONNECTING))return;
    try{
      const settings=await api.json<{configured:boolean;liveEnabled:boolean}>('/v1/class-speech-settings');
      if(!settings.configured||!settings.liveEnabled||stopped)return;
      const latest=getRecord();
      const result=await api.json<{ticket:string;url:string;reservationId:string}>(`/v1/class-sessions/${record.classSetup!.classId}/transcription-sessions`,{method:'POST',headers:{'X-Capture-Capability':await captureCredential(record),'Idempotency-Key':Crypto.randomUUID()},body:JSON.stringify({anchorMs:(latest.classSetup?.startMs||0)+latest.durationMs})});
      if(stopped){await api.json(`/v1/class-sessions/${record.classSetup!.classId}/transcription-sessions/${result.reservationId}/cancel`,{method:'POST'}).catch(()=>undefined);return;}
      const current=new WebSocket(result.url);socket=current;let rotate=false;
      current.onopen=()=>current.send(JSON.stringify({ticket:result.ticket}));
      current.onmessage=event=>{try{const data=JSON.parse(String(event.data));if(data.type==='ready'){retries=0;phase=sum=count=position=0;void Capture.setLivePcmEnabled(true);onStatus('Live captions connected');}else if(data.type==='rotate'){rotate=true;current.close();}else if(data.type==='error')onStatus(data.message);}catch{current.close();}};
      current.onclose=()=>{void Capture.setLivePcmEnabled(false);if(stopped)return;if(!rotate&&++retries>4){onStatus('Live captions disconnected. Recorded audio remains saved.');return;}timer=setTimeout(()=>void connect(),rotate?300:Math.min(10000,1000*2**retries));};
    }catch{onStatus('Live captions unavailable. Recorded audio is still saved.');}
  }
  const state=AppState.addEventListener('change',value=>{if(value==='active')void connect();else{void Capture.setLivePcmEnabled(false);socket?.close();}});
  void connect();
  return()=>{stopped=true;if(timer)clearTimeout(timer);subscription.remove();state.remove();void Capture.setLivePcmEnabled(false);socket?.close();};
}
