import {expect,it,vi} from 'vitest';
vi.mock('@/lib/lecture-local-store',()=>({createLocalLecture:vi.fn(),getLocalLecture:vi.fn(),persistAudioSlice:vi.fn(),updateLocalLecture:vi.fn(),defaultLecturePreferences:{}}));
vi.mock('@/lib/lecture-upload-queue',()=>({syncLecture:vi.fn()}));
import {lectureCapture} from '@/lib/lecture-capture';
import {createLocalLecture,getLocalLecture,updateLocalLecture} from '@/lib/lecture-local-store';
it('does not start a microphone on import and leaves no manifest when permission is denied',async()=>{
 const getUserMedia=vi.fn().mockRejectedValue(new DOMException('Permission denied','NotAllowedError'));
 Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{getUserMedia}});
 vi.stubGlobal('MediaRecorder',class {});
 expect(getUserMedia).not.toHaveBeenCalled();
 await expect(lectureCapture.start({title:'Class',ownerId:'alice',microphoneId:'chosen-mic'})).rejects.toThrow('Permission denied');
 expect(getUserMedia).toHaveBeenCalledWith({audio:{echoCancellation:true,noiseSuppression:true,deviceId:{exact:'chosen-mic'}}});
 expect(createLocalLecture).not.toHaveBeenCalled();expect(lectureCapture.mediaStream).toBeNull();expect(lectureCapture.phase).toBe('idle');
 vi.unstubAllGlobals();
});

it('releases the microphone as soon as Stop is pressed, before pending audio saves',async()=>{
 const stopTrack=vi.fn();const track={readyState:'live',stop:stopTrack,addEventListener:vi.fn(),removeEventListener:vi.fn()};
 const stream={getTracks:()=>[track],getAudioTracks:()=>[track]};
 Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{getUserMedia:vi.fn().mockResolvedValue(stream)}});
 let finishRecorder!:(()=>void);
 class Recorder {
  static isTypeSupported(){return true;}
  state='inactive';mimeType='audio/webm';ondataavailable:((value:{data:Blob})=>void)|null=null;onstop:(()=>void)|null=null;
  start(){this.state='recording';}
  stop(){this.state='inactive';finishRecorder=()=>{this.ondataavailable?.({data:new Blob(['audio'])});this.onstop?.();};}
 }
 vi.stubGlobal('MediaRecorder',Recorder);
 vi.mocked(getLocalLecture).mockResolvedValue({nextSequenceNumber:1} as Awaited<ReturnType<typeof getLocalLecture>>);
 await lectureCapture.start({title:'Biology',ownerId:'alice'});
 const stopping=lectureCapture.stop();
 expect(stopTrack).toHaveBeenCalled();expect(lectureCapture.phase).toBe('finalizing');
 finishRecorder();await stopping;
 for(let i=0;i<8;i++)await Promise.resolve();
 expect(updateLocalLecture).toHaveBeenCalledWith(expect.any(String),expect.objectContaining({phase:'stop_requested',expectedChunkCount:1}));
 expect(lectureCapture.phase).toBe('saved');vi.unstubAllGlobals();
});
