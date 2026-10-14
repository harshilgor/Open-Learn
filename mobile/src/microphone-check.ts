import {AudioModule,RecordingPresets,setAudioModeAsync} from 'expo-audio';
import {File} from 'expo-file-system';
import {AppState} from 'react-native';

// Explicit, local-only preflight. The short cache sample never enters the
// lecture journal or upload queue and is deleted after the check.
export async function checkPhoneMicrophone(signal:AbortSignal){
  const permission=await AudioModule.requestRecordingPermissionsAsync();
  if(!permission.granted)throw Error('Microphone permission is required for the input check.');
  if(signal.aborted)throw Error('Input check cancelled.');
  const recorder=new AudioModule.AudioRecorder({...RecordingPresets.LOW_QUALITY,isMeteringEnabled:true,directory:'cache'});
  let peak=-160,clipping=0,interrupted=false;
  try{
    await setAudioModeAsync({allowsRecording:true,playsInSilentMode:true});
    await recorder.prepareToRecordAsync();
    if(signal.aborted)throw Error('Input check cancelled.');
    recorder.recordForDuration(5);
    await new Promise<void>(resolve=>{
      const sample=setInterval(()=>{const level=recorder.getStatus().metering;if(typeof level==='number'){peak=Math.max(peak,level);if(level>-1)clipping++;}},200);
      const done=()=>{clearInterval(sample);clearTimeout(end);signal.removeEventListener('abort',done);listener.remove();resolve();};
      const listener=AppState.addEventListener('change',state=>{if(state!=='active'){interrupted=true;done();}});
      const end=setTimeout(done,5000);signal.addEventListener('abort',done,{once:true});
    });
    if(signal.aborted)throw Error('Input check cancelled.');
    if(interrupted)return 'Input check interrupted. Keep the app open and try again.';
    return clipping>2?'Input is clipping. Move farther from the microphone.':peak<-45?'Very little input detected. Move the phone closer to the speaker.':'Input detected. Place the phone near the speaker; this does not measure transcription accuracy.';
  }finally{
    try{if(recorder.isRecording)await recorder.stop();}finally{
      const uri=recorder.uri;recorder.release();
      if(uri){const sample=new File(uri);if(sample.exists)sample.delete();}
    }
  }
}
