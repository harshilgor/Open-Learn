import {allowedUrl, validateCommand, safeControl} from './companion-policy.js';
import {openLearnCanvasRead} from './canvas-read.js';

const busy = new Set();
const attachedTabs = new Set();

async function request(config, path, init = {}) {
  const response = await fetch(config.backend.replace(/\/$/, '') + path, {...init, headers: {
    'Content-Type':'application/json', Authorization:'Bearer ' + config.authToken,
    ...(config.desktopToken ? {'X-Forma-Desktop-Token':config.desktopToken} : {}), ...init.headers}});
  if (!response.ok) throw Error(response.status === 401 ? 'login_required' : 'outcome_unknown');
  return response.json();
}

async function storeStatus(message) { await chrome.storage.local.set({companionStatus: message}); }

async function observe(tabId,query) {
  await chrome.scripting.executeScript({target:{tabId}, files:['observer.js']});
  const result = await chrome.scripting.executeScript({target:{tabId}, args:[query || ''],func:query=>openLearnObserve(query)});
  return result[0].result;
}

async function tabFor(command, config) {
  const {taskTabs = {}} = await chrome.storage.local.get('taskTabs');
  const mapping = taskTabs[command.taskId];
  if (mapping) {
    try {
      const tab = await chrome.tabs.get(mapping.tabId);
      if (!allowedUrl(tab.url, config)) throw Error('origin_not_approved');
      return tab;
    } catch (error) {
      if (String(error.message) === 'origin_not_approved') throw error;
      throw Error('tab_closed');
    }
  }
  const tab = await chrome.tabs.create({url:command.action.url || config.origin, active:false});
  taskTabs[command.taskId] = {tabId:tab.id, deviceId:config.deviceId};
  await chrome.storage.local.set({taskTabs});
  return tab;
}

async function ready(tabId) {
  for (let n=0; n<40; n++) {
    const tab = await chrome.tabs.get(tabId);
    if (tab.status === 'complete') return;
    await new Promise(resolve=>setTimeout(resolve,250));
  }
}

async function attach(tabId) {
  if(attachedTabs.has(tabId)) return;
  try { await chrome.debugger.attach({tabId}, '1.3'); attachedTabs.add(tabId); }
  catch {
    try {await chrome.debugger.sendCommand({tabId},'Page.getFrameTree');attachedTabs.add(tabId);}
    catch {throw Error('capability_unavailable');}
  }
  await chrome.debugger.sendCommand({tabId},'Fetch.enable',{patterns:[{urlPattern:'*',requestStage:'Request'}]});
}
chrome.debugger.onDetach.addListener(source=>attachedTabs.delete(source.tabId));
chrome.debugger.onEvent.addListener((source,method,params)=>{
  if(method!=='Fetch.requestPaused' || !attachedTabs.has(source.tabId))return;
  const readOnly=['GET','HEAD','OPTIONS'].includes(params.request.method);
  void chrome.debugger.sendCommand(source,readOnly?'Fetch.continueRequest':'Fetch.failRequest',readOnly?{requestId:params.requestId}:{requestId:params.requestId,errorReason:'BlockedByClient'}).catch(()=>undefined);
});

async function interact(tabId, command, config) {
  const action = command.action;
  const page = await observe(tabId);
  if (command.snapshotBasis && page.documentRevision !== command.snapshotBasis) throw Error('stale_reference');
  const control = safeControl(page.controls.find(c=>c.ref===action.elementRef), action, config);
  await attach(tabId);
  if (action.tool === 'click') {
    const scroll = await chrome.scripting.executeScript({target:{tabId}, args:[action.elementRef], func: ref => {
      const el = document.querySelector(`[data-openlearn-ref="${CSS.escape(ref)}"]`);
      if (!el) return null;
      el.scrollIntoView({block:'center'}); const box=el.getBoundingClientRect();
      return {x:box.x+box.width/2,y:box.y+box.height/2};
    }});
    const point = scroll[0].result; if (!point) throw Error('stale_reference');
    for (const type of ['mousePressed','mouseReleased']) await chrome.debugger.sendCommand({tabId}, 'Input.dispatchMouseEvent', {...point,type,button:'left',clickCount:1});
  } else if (action.tool === 'fill') {
    await chrome.scripting.executeScript({target:{tabId},args:[action.elementRef],func:ref=>{
      const el=document.querySelector(`[data-openlearn-ref="${CSS.escape(ref)}"]`); if (el) {el.focus();el.select?.();}
    }});
    await chrome.debugger.sendCommand({tabId},'Input.insertText',{text:action.value || ''});
  } else {
    const key = action.value;
    await chrome.debugger.sendCommand({tabId},'Input.dispatchKeyEvent',{type:'keyDown',key,code:key,windowsVirtualKeyCode:key==='Enter'?13:key==='Escape'?27:key==='Tab'?9:0});
    await chrome.debugger.sendCommand({tabId},'Input.dispatchKeyEvent',{type:'keyUp',key,code:key});
  }
  await ready(tabId);
  return observe(tabId);
}

function platformUrl(command) {
  const action=command.action, c=action.externalCourseId;
  if (action.resource !== 'courses' && !/^\d+$/.test(c || '')) throw Error('origin_not_approved');
  const now=new Date(), until=new Date(Date.now()+180*86400000);
  const routes={courses:'/api/v1/courses?enrollment_state=active&enrollment_type=student&include[]=term&per_page=100',
    assignments:`/api/v1/courses/${c}/assignments?override_assignment_dates=true&per_page=100`,
    syllabus:`/api/v1/courses/${c}?include[]=syllabus_body`,
    announcements:`/api/v1/announcements?context_codes[]=course_${c}&per_page=100`,
    modules:`/api/v1/courses/${c}/modules?include[]=items&per_page=100`,
    calendar:`/api/v1/calendar_events?context_codes[]=course_${c}&start_date=${new Date(now-30*86400000).toISOString().slice(0,10)}&end_date=${until.toISOString().slice(0,10)}&per_page=100`};
  const base=new URL(routes[action.resource],command.origin);
  if (!action.cursor) return base.href;
  const next=new URL(action.cursor);
  if (next.origin!==base.origin || next.pathname!==base.pathname) throw Error('origin_not_approved');
  for (const [key,value] of base.searchParams) if (!['page','per_page'].includes(key) && next.searchParams.get(key)!==value) throw Error('origin_not_approved');
  return next.href;
}

async function documentRead(tabId, command) {
  const result = await chrome.scripting.executeScript({target:{tabId}, world:'MAIN', args:[command.action.url,command.origin,command.approvedOrigins], func:async(url,origin,approved)=>{
    if (![origin,...approved].includes(new URL(url).origin)) throw Error('origin_not_approved');
    const response=await fetch(url,{credentials:'same-origin',redirect:'error'});
    if (!response.ok) throw Error('unsupported_file');
    const bytes=new Uint8Array(await response.arrayBuffer()); if (bytes.length>8000000) throw Error('unsupported_file');
    const type=response.headers.get('content-type') || '';
    if (type.startsWith('text/')) return {url,documentRevision:String(bytes.length),documentText:new TextDecoder().decode(bytes).slice(0,150000),blocks:[],controls:[],status:'completed'};
    // PDFs are uploaded as bounded binary document evidence; backend uses its existing parser.
    let binary=''; for(let n=0;n<bytes.length;n+=8192) binary+=String.fromCharCode(...bytes.subarray(n,n+8192));
    return {url,contentType:type,documentBytes:btoa(binary)};
  }});
  return result[0].result;
}

async function execute(command, config) {
  validateCommand(command,config);
  const tab=await tabFor(command,config); await ready(tab.id);
  const action=command.action;
  if (action.tool==='navigate') {await chrome.tabs.update(tab.id,{url:action.url});await ready(tab.id);}
  const current=await chrome.tabs.get(tab.id); if (!allowedUrl(current.url,config)) throw Error('login_required');
  let observation;
  if (action.tool==='read_platform_resource') {
    const result=await chrome.scripting.executeScript({target:{tabId:tab.id},world:'MAIN',args:[{origin:command.origin,url:platformUrl(command)}],func:openLearnCanvasRead});
    observation=result[0].result;
  } else if (['click','fill','press_key'].includes(action.tool)) observation=await interact(tab.id,command,config);
  else if (action.tool==='scroll') {
    await chrome.scripting.executeScript({target:{tabId:tab.id},args:[action.elementRef,action.direction==='down'?action.amount:-action.amount],func:(ref,amount)=>{
      const el=ref?document.querySelector(`[data-openlearn-ref="${CSS.escape(ref)}"]`):window;
      if(!el) throw Error('stale_reference');el.scrollBy(0,amount);
    }});
    await new Promise(resolve=>setTimeout(resolve,350)); observation=await observe(tab.id);
  } else if (action.tool==='capture_screenshot') {
    observation=await observe(tab.id);
    if(observation.status!=='login_required') {
      await attach(tab.id);
      const screenshot=await chrome.debugger.sendCommand({tabId:tab.id},'Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
      const fresh=await observe(tab.id);
      observation=fresh;
      if(fresh.status!=='login_required')observation.screenshot=screenshot.data;
    }
  } else if (action.tool==='read_document') {
    const document=await documentRead(tab.id,command);
    if(document.documentBytes) return {generation:command.generation,connectionRevision:command.connectionRevision,document};
    observation=document;
  } else observation=await observe(tab.id,action.tool==='find'?action.query:undefined);
  observation.tabId=String(tab.id);
  if (!allowedUrl(observation.url,config)) throw Error('origin_not_approved');
  if (command.accountId && observation.accountId && command.accountId!==observation.accountId) throw Error('account_changed');
  return {generation:command.generation,connectionRevision:command.connectionRevision,observation};
}

async function poll(config) {
  if(busy.has(config.deviceId)) return;
  busy.add(config.deviceId);
  try {
    const {commands,activeTaskIds=[],handoffs=[]}=await request(config,'/v1/browser-devices/commands');
    const {taskTabs={}}=await chrome.storage.local.get('taskTabs');
    for(const [id,mapping] of Object.entries(taskTabs)) {
      if(mapping.deviceId!==config.deviceId) continue;
      // Release debugger access while idle, including login handoffs and stopped tasks.
      if(!commands.some(command=>command.taskId===id)) {
        try {await chrome.debugger.detach({tabId:mapping.tabId});} catch { /* Already detached. */ }
        attachedTabs.delete(mapping.tabId);
      }
      if(!activeTaskIds.includes(id)) delete taskTabs[id];
    }
    await chrome.storage.local.set({taskTabs});
    // This poll is serialized after any in-flight command. No human-ready
    // acknowledgement is sent until debugger input has been detached.
    for(const handoff of handoffs) {
      let mapping=taskTabs[handoff.taskId];
      if(!mapping) {
        const tab=await chrome.tabs.create({url:config.origin,active:true});
        mapping=taskTabs[handoff.taskId]={tabId:tab.id,deviceId:config.deviceId};
        await chrome.storage.local.set({taskTabs});
      }
      try {await chrome.debugger.detach({tabId:mapping.tabId});}catch{/* Verify detachment below. */}
      let stillAttached=false;
      try {await chrome.debugger.sendCommand({tabId:mapping.tabId},'Page.getFrameTree');stillAttached=true;}catch{/* Detached. */}
      if(stillAttached)throw Error('outcome_unknown');
      attachedTabs.delete(mapping.tabId);
      await request(config,`/v1/browser-devices/handoffs/${handoff.taskId}/ack`,{method:'POST',body:JSON.stringify({generation:handoff.generation})});
      await chrome.tabs.update(mapping.tabId,{active:true});
      await storeStatus('You control the browser. Return control in OpenLearn when ready.');
    }
    const {commandReceipts={}}=await chrome.storage.local.get('commandReceipts');
    for(const command of commands) {
      let receipt=commandReceipts[command.id];
      if(receipt && receipt.generation!==command.generation) receipt=null;
      if(!receipt) {
        commandReceipts[command.id]={generation:command.generation,inProgress:true};
        await chrome.storage.local.set({commandReceipts});
        try {receipt=await execute(command,config);}
        catch(error) {
          const allowed=['login_required','device_offline','tab_closed','stale_reference','origin_not_approved','capability_unavailable','unsupported_file','action_blocked','outcome_unknown','account_changed'];
          receipt={generation:command.generation,connectionRevision:command.connectionRevision,error:allowed.includes(error.message)?error.message:'outcome_unknown'};
        }
      } else if(receipt.inProgress) receipt={generation:command.generation,connectionRevision:command.connectionRevision,error:'outcome_unknown'};
      commandReceipts[command.id]=receipt; await chrome.storage.local.set({commandReceipts});
      await request(config,`/v1/browser-devices/commands/${command.id}/result`,{method:'POST',body:JSON.stringify(receipt)});
      await storeStatus(receipt.error?`Task needs attention: ${receipt.error.replaceAll('_',' ')}`:'Website task is running.');
    }
    const entries=Object.entries(commandReceipts).slice(-40);
    await chrome.storage.local.set({commandReceipts:Object.fromEntries(entries)});
    return commands.length;
  } catch(error) {await storeStatus('Open OpenLearn and check the browser connection.');}
  finally {busy.delete(config.deviceId);}
}

async function tick() {
  const {companionConnections=[]}=await chrome.storage.local.get('companionConnections');
  for(const config of companionConnections) {
    const until=Date.now()+25000;
    let count=await poll(config),idle=0;
    const active=!!count;
    while(active && idle<4 && Date.now()<until) {
      await new Promise(resolve=>setTimeout(resolve,750));
      count=await poll(config);
      idle=count?0:idle+1;
    }
  }
}
chrome.alarms.onAlarm.addListener(alarm=>{if(alarm.name==='openlearn-poll') void tick();});
chrome.runtime.onStartup.addListener(()=>void tick());
chrome.runtime.onInstalled.addListener(()=>{chrome.alarms.create('openlearn-poll',{periodInMinutes:0.5});});
chrome.runtime.onMessage.addListener((message,_sender,reply)=>{
  if(message.type==='companion-pair') {
    (async()=>{
      const config=message.config;
      if(config.kind!=='browser' || !config.authToken || !config.deviceId || !config.connectionId) throw Error('Invalid pairing configuration.');
      const backend=new URL(config.backend);
      if(backend.protocol!=='https:' && !(backend.hostname==='127.0.0.1' && backend.protocol==='http:')) throw Error('Use HTTPS or the local OpenLearn companion.');
      const {companionConnections=[]}=await chrome.storage.local.get('companionConnections');
      await chrome.storage.local.set({companionConnections:[...companionConnections.filter(c=>c.connectionId!==config.connectionId),config]});
      await chrome.alarms.create('openlearn-poll',{periodInMinutes:0.5});
      await storeStatus('Connected. Ask OpenLearn to read this website.'); await tick(); reply({ok:true});
    })().catch(error=>reply({error:error.message}));return true;
  }
  if(message.type==='companion-poll') {void tick().then(()=>reply({ok:true}));return true;}
  if(message.type==='companion-disconnect') {
    (async()=>{
      const {companionConnections=[]}=await chrome.storage.local.get('companionConnections');
      for(const config of companionConnections) { try {await request(config,'/v1/browser-devices/disconnect',{method:'POST'});} catch { /* Backend revocation remains available in OpenLearn. */ } }
      const {taskTabs={}}=await chrome.storage.local.get('taskTabs');
      for(const task of Object.values(taskTabs)) {try{await chrome.debugger.detach({tabId:task.tabId});}catch{/* May not be attached. */}}
      await chrome.storage.local.remove(['companionConnections','taskTabs','commandReceipts']);await storeStatus('Disconnected.');reply({ok:true});
    })();return true;
  }
});
