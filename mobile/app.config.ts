import type {ExpoConfig} from 'expo/config';
const config:ExpoConfig={
  name:'Open Learn',slug:'openlearn',version:'0.1.0',scheme:'openlearn',
  orientation:'default',userInterfaceStyle:'automatic',
  ios:{bundleIdentifier:process.env.EXPO_PUBLIC_IOS_BUNDLE_ID || 'dev.openlearn.app',supportsTablet:true,infoPlist:{NSMicrophoneUsageDescription:'Record voice messages and save lectures for your course.',UIBackgroundModes:['audio'],ITSAppUsesNonExemptEncryption:false}},
  android:{package:process.env.EXPO_PUBLIC_ANDROID_PACKAGE || 'dev.openlearn.app',permissions:['RECORD_AUDIO','FOREGROUND_SERVICE','FOREGROUND_SERVICE_MICROPHONE','POST_NOTIFICATIONS']},
  platforms:['ios','android'],
  plugins:['expo-secure-store','expo-notifications','expo-document-picker','expo-web-browser','expo-sharing','expo-audio','expo-sqlite'],
  extra:{eas:{projectId:process.env.EXPO_PUBLIC_EAS_PROJECT_ID}},
};
export default config;
