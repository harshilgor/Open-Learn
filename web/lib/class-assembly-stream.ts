import {request} from './api';

const EVENT='open-learn-live-lecture-transcription';
export class AssemblyClassStream {
  private socket:WebSocket|null=null;
  private processor:AudioWorkletNode|null=null;
  private source:MediaStreamAudioSourceNode|null=null;
  private sink:GainNode|null=null;
  private stopped=true;
  private retries=0;
  private timer:ReturnType<typeof setTimeout>|null=null;
  private turns:{id:string;text:string}[]=[];
  private reservationId:string|null=null;
  constructor(private readonly recordingId:string,private readonly elapsed:()=>number){}
  private publish(status:string,interim='',error?:string){window.dispatchEvent(new CustomEvent(EVENT,{detail:{recordingId:this.recordingId,status,turns:this.turns.slice(-20),persistedTurnIds:this.turns.map(turn=>turn.id),interim,...(error?{error}: {})}}));}
  async start(stream:MediaStream,capability:string,context:AudioContext):Promise<void>{
    this.stopped=false;this.publish('connecting');
    const classId='class_'+this.recordingId;
    try{
      const result=await request<{ticket:string;url:string;reservationId:string}>(`/v1/class-sessions/${encodeURIComponent(classId)}/transcription-sessions`,{method:'POST',headers:{'X-Capture-Capability':capability,'Idempotency-Key':crypto.randomUUID()},body:JSON.stringify({anchorMs:Math.round(this.elapsed())})});
      if(this.stopped){await request(`/v1/class-sessions/${encodeURIComponent(classId)}/transcription-sessions/${result.reservationId}/cancel`,{method:'POST'});return;}
      this.reservationId=result.reservationId;
      await context.audioWorklet.addModule('/class-audio-worklet.js');
      if(this.stopped){await request(`/v1/class-sessions/${encodeURIComponent(classId)}/transcription-sessions/${result.reservationId}/cancel`,{method:'POST'}).catch(()=>undefined);return;}
      const socket=new WebSocket(result.url);this.socket=socket;
      socket.onopen=()=>socket.send(JSON.stringify({ticket:result.ticket}));
      let rotate=false;
      socket.onmessage=event=>{
        if(this.stopped)return;
        try{
          const message=JSON.parse(String(event.data)) as {type:string;text?:string;final?:boolean;sequence?:number;streamId?:string;message?:string;itemId?:string};
          if(message.type==='ready'){
            this.retries=0;
            this.source=context.createMediaStreamSource(stream);this.processor=new AudioWorkletNode(context,'class-audio');
            this.sink=context.createGain();this.sink.gain.value=0;
            this.processor.port.onmessage=frame=>{
              if(socket.readyState!==WebSocket.OPEN||this.stopped)return;
              if(socket.bufferedAmount>64000){this.publish('error','','Live captions are catching up. Saved audio continues recording.');socket.close();return;}
              socket.send(frame.data as ArrayBuffer);
            };
            this.source.connect(this.processor);this.processor.connect(this.sink);this.sink.connect(context.destination);
            this.publish('connected');
          }else if(message.type==='caption'){
            if(message.final&&message.text){const id=message.itemId||result.reservationId+':'+message.sequence;this.turns=[...this.turns.filter(turn=>turn.id!==id),{id,text:message.text}].slice(-20);this.publish('connected');}
            else this.publish('connected',message.text||'');
          }else if(message.type==='rotate'){rotate=true;socket.close();}
          else if(message.type==='error'){this.publish('error','',message.message);}
        }catch{this.publish('error','','The live caption connection returned invalid data.');socket.close();}
      };
      socket.onclose=()=>{
        this.detach();
        if(this.stopped)return;
        if(!rotate&&++this.retries>4){this.publish('error','','Live captions stopped after repeated connection failures. Recorded audio remains available.');return;}
        this.publish('connecting');this.timer=setTimeout(()=>void this.start(stream,capability,context),rotate?200:Math.min(10000,1000*2**this.retries));
      };
      socket.onerror=()=>this.publish('error','','Live captions disconnected; recorded audio is still saved.');
    }catch{
      if(this.reservationId)void request(`/v1/class-sessions/${encodeURIComponent(classId)}/transcription-sessions/${this.reservationId}/cancel`,{method:'POST'}).catch(()=>undefined);
      this.publish('error','','Live captions could not connect. Saved audio continues recording.');
    }
  }
  private detach(){this.processor?.disconnect();this.source?.disconnect();this.sink?.disconnect();if(this.processor)this.processor.port.onmessage=null;this.processor=null;this.source=null;this.sink=null;}
  pause(){this.stop();this.publish('paused');}
  stop(){this.stopped=true;if(this.timer)clearTimeout(this.timer);this.timer=null;this.detach();this.socket?.close();this.socket=null;this.publish('stopped');}
}
