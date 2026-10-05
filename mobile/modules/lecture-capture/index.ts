import {requireNativeModule} from 'expo-modules-core';
export type CaptureState={recordingId:string;directory:string;status:string;segments:{sequence:number;uri:string;startMs:number;endMs:number}[];interrupted:boolean;startedAtMs:number;durationMs:number};
export default requireNativeModule<{
  start(directory:string,recordingId:string):Promise<CaptureState>;
  stop():Promise<CaptureState>;
  pause():Promise<CaptureState>;
  resume():Promise<CaptureState>;
  inspect(directory:string):Promise<CaptureState>;
}>('LectureCapture');
