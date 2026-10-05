import {Directory,File,Paths} from 'expo-file-system';
import * as Sharing from 'expo-sharing';
import * as DocumentPicker from 'expo-document-picker';
import * as Crypto from 'expo-crypto';
import {api,authenticated,account} from './account';
import {journals} from './storage';
type FileUpload={sessionId:string;courseId?:string|null;uri:string;name:string;mime:string;materialId?:string;versionId?:string};
export async function download(id:string,name:string){
  const owner=account()?.owner;if(!owner)throw Error('Sign in first.');
  const response=await authenticated(`/v1/assistant/artifacts/${encodeURIComponent(id)}/download`);
  const namespace=await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256,owner);
  const folder=new Directory(Paths.document,'downloads',namespace);folder.create({intermediates:true,idempotent:true});
  const file=new File(folder,id+'_'+name.replace(/[^A-Za-z0-9_.-]/g,'_'));const bytes=new Uint8Array(await response.arrayBuffer());if(account()?.owner!==owner)throw Error('Account changed; download cancelled.');file.write(bytes);
  if(await Sharing.isAvailableAsync()){if(account()?.owner!==owner)throw Error('Account changed; sharing cancelled.');await Sharing.shareAsync(file.uri);}return file.uri;
}
export async function pickAndAttach(sessionId:string,courseId?:string|null){
  const owner=account()?.owner;if(!owner)throw Error('Sign in first.');
  if(await journals.read('file-upload:'+owner))throw Error('Retry the saved attachment before selecting another file.');
  const choice=await DocumentPicker.getDocumentAsync({copyToCacheDirectory:true,multiple:false});if(choice.canceled)return;
  const asset=choice.assets[0];if((asset.size||0)>24*1024*1024)throw Error('Choose a file smaller than 24 MB.');
  const mime=/\.(csv|txt)$/i.test(asset.name)?'text/plain':/\.md$/i.test(asset.name)?'text/markdown':asset.mimeType||'application/octet-stream';
  if(!['application/pdf','text/plain','text/markdown','image/png','image/jpeg','image/webp','image/gif'].includes(mime))throw Error('Choose a PDF, CSV, text, Markdown or supported image file.');
  const namespace=await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256,owner);
  const folder=new Directory(Paths.document,'uploads',namespace);folder.create({intermediates:true,idempotent:true});
  const file=new File(folder,Crypto.randomUUID());new File(asset.uri).copy(file);
  if(account()?.owner!==owner)throw Error('Account changed; attachment cancelled.');
  const upload:FileUpload={sessionId,courseId,uri:file.uri,name:asset.name,mime};
  await journals.write('file-upload:'+owner,upload);await retryAttachment(owner,courseId);
}
export async function retryAttachment(owner:string,courseId?:string|null){
  if(account()?.owner!==owner)throw Error('Account changed; upload paused.');
  const upload=await journals.read<FileUpload>('file-upload:'+owner);if(!upload)return;
  const bytes=await new File(upload.uri).bytes();
  if(account()?.owner!==owner)throw Error('Account changed; upload paused.');
  if(!upload.materialId){const result=await api.json<{materialId:string;versionId:string}>('/v1/materials',{method:'POST',body:JSON.stringify({title:upload.name,mediaType:upload.mime,byteCount:bytes.length,role:'reference',courseId:upload.courseId})});upload.materialId=result.materialId;upload.versionId=result.versionId;await journals.write('file-upload:'+owner,upload);}
  await api.binary(`/v1/materials/${upload.materialId}/versions/${upload.versionId}/content`,bytes,{'Content-Type':upload.mime});
  await api.json(`/v1/sessions/${upload.sessionId}/materials`,{method:'POST',body:JSON.stringify({materialVersionId:upload.versionId})});
  if(upload.name.toLowerCase().endsWith('.csv'))await journals.write('analysis-input:'+owner+':'+upload.sessionId,upload.versionId);
  await journals.write('file-upload:'+owner,null);
}
