import * as AuthSession from 'expo-auth-session';
import * as SecureStore from 'expo-secure-store';
import * as WebBrowser from 'expo-web-browser';
import {ApiError,type Transport} from './protocol';
WebBrowser.maybeCompleteAuthSession();
type Session={accessToken:string;refreshToken?:string;expiresAt:number;owner:string;name:string};
const origin=process.env.EXPO_PUBLIC_API_URL || '';
const issuer=process.env.EXPO_PUBLIC_OIDC_ISSUER || '';
const clientId=process.env.EXPO_PUBLIC_OIDC_CLIENT_ID || '';
let session:Session|null=null;
let epoch=0;
let refreshing:Promise<void>|null=null;
function configured(){if(!origin.startsWith('https://') || !issuer.startsWith('https://') || !clientId)throw Error('Configure the HTTPS API and native account client first.');}
async function verify(accessToken:string){const response=await fetch(origin+'/v1/account',{headers:{Authorization:'Bearer '+accessToken}});if(!response.ok)throw Error('Account verification failed.');return await response.json() as {ownerId:string;displayName:string};}
async function save(value:Session){await SecureStore.setItemAsync('openlearn-session',JSON.stringify(value));session=value;}
export async function restoreAccount(){configured();const saved=await SecureStore.getItemAsync('openlearn-session');if(saved)session=JSON.parse(saved);return session;}
export async function signIn(){
  configured();const discovery=await AuthSession.fetchDiscoveryAsync(issuer);
  const redirectUri=AuthSession.makeRedirectUri({scheme:'openlearn',path:'auth'});
  const request=new AuthSession.AuthRequest({clientId,redirectUri,responseType:AuthSession.ResponseType.Code,usePKCE:true,scopes:['openid','profile','offline_access'],extraParams:process.env.EXPO_PUBLIC_OIDC_AUDIENCE?{audience:process.env.EXPO_PUBLIC_OIDC_AUDIENCE}:{}});
  const result=await request.promptAsync(discovery);
  if(result.type!=='success')return null;
  const tokens=await AuthSession.exchangeCodeAsync({clientId,code:result.params.code,redirectUri,extraParams:{code_verifier:request.codeVerifier!}},discovery);
  const identity=await verify(tokens.accessToken);epoch++;
  await save({accessToken:tokens.accessToken,refreshToken:tokens.refreshToken,expiresAt:Date.now()+((tokens.expiresIn||300)*1000),owner:identity.ownerId,name:identity.displayName});return session;
}
export async function signOut(){epoch++;session=null;await SecureStore.deleteItemAsync('openlearn-session');}
async function token(){
  if(!session)throw new ApiError(401,'Sign in to continue.');
  if(session.expiresAt<=Date.now()+30000){
    if(!session.refreshToken)throw new ApiError(401,'Sign in again; local pending work is retained.');
    const version=epoch,old=session;
    refreshing ||= (async()=>{
      const discovery=await AuthSession.fetchDiscoveryAsync(issuer);
      const tokens=await AuthSession.refreshAsync({clientId,refreshToken:old.refreshToken!},discovery);
      const identity=await verify(tokens.accessToken);
      if(version!==epoch || identity.ownerId!==old.owner)throw new ApiError(401,'Account changed. Sign in again.');
      await save({...old,accessToken:tokens.accessToken,refreshToken:tokens.refreshToken||old.refreshToken,expiresAt:Date.now()+((tokens.expiresIn||300)*1000)});
    })().finally(()=>{refreshing=null});
    await refreshing;
  }
  return session!.accessToken;
}
export async function authenticated(path:string,init:RequestInit={}){
  if(!path.startsWith('/v1/'))throw Error('Unsupported API route.');
  const version=epoch;const headers=new Headers(init.headers);headers.set('Authorization','Bearer '+await token());
  if(epoch!==version)throw new ApiError(401,'Account changed.');
  const response=await fetch(origin+path,{...init,headers});
  if(epoch!==version)throw new ApiError(401,'Account changed.');
  if(!response.ok){let message='Request failed. Pending work is retained.';try{const body=await response.json();message=body.detail?.message||message;}catch{}throw new ApiError(response.status,message);}
  return response;
}
export const api:Transport={
  async json<T>(path:string,init:RequestInit={}){const headers=new Headers(init.headers);if(init.body)headers.set('Content-Type','application/json');const response=await authenticated(path,{...init,headers});return (response.status===204?undefined:await response.json()) as T;},
  async binary<T>(path:string,bytes:Uint8Array,headers:Record<string,string>){const response=await authenticated(path,{method:'PUT',headers,body:bytes as unknown as BodyInit});return await response.json() as T;},
};
export function account(){return session;}
