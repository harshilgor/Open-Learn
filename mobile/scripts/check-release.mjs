// Validate public release configuration without printing credentials.
try { process.loadEnvFile('.env'); } catch (error) { if (error.code !== 'ENOENT') throw error; }
const httpsKeys=['EXPO_PUBLIC_API_URL','EXPO_PUBLIC_OIDC_ISSUER'];
const missing=[];
for(const key of httpsKeys){try{if(new URL(process.env[key]).protocol!=='https:')missing.push(key)}catch{missing.push(key)}}
for(const key of ['EXPO_PUBLIC_OIDC_CLIENT_ID','EXPO_PUBLIC_OIDC_AUDIENCE','EXPO_PUBLIC_EAS_PROJECT_ID','EXPO_PUBLIC_IOS_BUNDLE_ID','EXPO_PUBLIC_ANDROID_PACKAGE'])if(!process.env[key])missing.push(key);
for(const key of ['EXPO_PUBLIC_IOS_BUNDLE_ID','EXPO_PUBLIC_ANDROID_PACKAGE'])if(process.env[key]==='dev.openlearn.app')missing.push(key+' (replace development identifier)');
if(missing.length){process.stderr.write('Configure release values: '+missing.join(', ')+'\n');process.exitCode=1}else process.stdout.write('Release configuration shape valid; account registration and connectivity still need acceptance.\n');
