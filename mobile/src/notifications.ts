import * as Notifications from 'expo-notifications';
import {Platform} from 'react-native';
import {api} from './account';
import {safeDeepLink} from './protocol';
import * as SecureStore from 'expo-secure-store';
Notifications.setNotificationHandler({handleNotification:async()=>({shouldPlaySound:false,shouldSetBadge:false,shouldShowBanner:true,shouldShowList:true})});
export async function enablePush(){
  const projectId=process.env.EXPO_PUBLIC_EAS_PROJECT_ID;if(!projectId)throw Error('Native push requires this build’s Expo project configuration.');
  if(Platform.OS==='android')await Notifications.setNotificationChannelAsync('default',{name:'Open Learn updates',importance:Notifications.AndroidImportance.DEFAULT});
  let permission=await Notifications.getPermissionsAsync();if(permission.status!=='granted')permission=await Notifications.requestPermissionsAsync();
  if(permission.status!=='granted')return false;
  const token=(await Notifications.getExpoPushTokenAsync({projectId})).data;
  await api.json('/v1/assistant/responsibility-push-token',{method:'POST',body:JSON.stringify({token})});await SecureStore.setItemAsync('openlearn-push-token',token);return true;
}
export async function disablePush(){const token=await SecureStore.getItemAsync('openlearn-push-token');if(token){await api.json('/v1/mobile/push-token/unlink',{method:'POST',body:JSON.stringify({token})});await SecureStore.deleteItemAsync('openlearn-push-token');}}
export function notificationLink(response:Notifications.NotificationResponse){const url=response.notification.request.content.data?.url;return typeof url==='string'?safeDeepLink(url):null;}
