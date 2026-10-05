const status = document.querySelector('#status');
const skills = ['courses', 'assignments', 'modules', 'announcements', 'syllabus', 'calendar'];
function validate(config) {
  const institution = new URL(config.origin);
  const backend = new URL(config.backend);
  if (institution.protocol !== 'https:' || institution.origin !== config.origin || institution.pathname !== '/' || !config.connectionId || !config.deviceId) throw Error('Invalid pairing configuration.');
  if (backend.protocol !== 'https:' && !(backend.hostname === '127.0.0.1' && backend.protocol === 'http:')) throw Error('Use HTTPS or the local companion.');
  if (config.kind === 'browser') { if (!config.authToken) throw Error('Missing browser grant.'); return config; }
  if (!config.courses || !config.grant || Object.keys(config.courses).some(id => !/^\d+$/.test(id))) throw Error('Canvas course IDs must be numeric.');
  return config;
}
document.querySelector('#pair').onclick = async () => {
  try {
    const config = validate(JSON.parse(document.querySelector('#config').value));
    const granted = await chrome.permissions.request({origins: [config.origin+'/*', ...(config.approvedOrigins || []).map(origin=>origin+'/*'), new URL(config.backend).origin+'/*']});
    if (!granted) throw Error('Institution access was declined.');
    if (config.kind === 'browser') {
      const result = await chrome.runtime.sendMessage({type:'companion-pair',config});
      if (result.error) throw Error(result.error);
      status.textContent='Connected. Ask OpenLearn to read this website. You can close this popup.';
      return;
    }
    // Short-lived Open Learn session credentials survive this browser session only.
    await chrome.storage.session.set({config}); status.textContent = 'Connected. Open the selected Canvas course before reading.';
  } catch (error) { status.textContent = error.message; }
};
document.querySelector('#sync').onclick = async () => {
  try {
    const {companionConnections=[]}=await chrome.storage.local.get('companionConnections');
    if (companionConnections.length) {await chrome.runtime.sendMessage({type:'companion-poll'});status.textContent='Checking OpenLearn tasks. Reads continue after closing this popup.';return;}
    const {config} = await chrome.storage.session.get('config'); validate(config);
    const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
    if (!tab?.url || new URL(tab.url).origin !== config.origin) throw Error('Select a tab at the approved Canvas institution.');
    status.textContent = 'Reading approved courses…';
    for (const [externalCourseId, courseId] of Object.entries(config.courses)) {
      for (const skill of skills) {
        const result = await chrome.scripting.executeScript({target: {tabId: tab.id}, world: 'MAIN', args: [config.origin, externalCourseId, skill], func: async (approvedOrigin, course, skill) => {
          if (location.origin !== approvedOrigin || !/^\d+$/.test(course)) throw Error('Browser scope changed.');
          const routes = {assignments: `/api/v1/courses/${course}/assignments?override_assignment_dates=true&per_page=100`, modules: `/api/v1/courses/${course}/modules?include[]=items&per_page=100`, announcements: `/api/v1/announcements?context_codes[]=course_${course}&per_page=100`, syllabus: `/api/v1/courses/${course}?include[]=syllabus_body`, calendar: `/api/v1/calendar_events?context_codes[]=course_${course}&per_page=100`, courses: `/api/v1/courses/${course}`};
          const courseResponse = await fetch(`${approvedOrigin}/api/v1/courses/${course}`, {credentials:'same-origin',method:'GET',redirect:'error'});
          if (!courseResponse.ok) return {items:[],complete:false,status:'login_required',checkpoint:routes[skill]};
          const courseInfo = await courseResponse.json();
          const student = courseInfo.enrollments?.find(e => ['student','StudentEnrollment'].includes(e.type));
          if (!student?.user_id) return {items:[],complete:false,status:'student_context_unconfirmed',checkpoint:routes[skill]};
          let next = new URL(routes[skill], approvedOrigin).href, items = [], pages = 0;
          const visited = new Set();
          while (next && pages++ < 20) {
            const url = new URL(next);
            if (url.origin !== approvedOrigin || !url.pathname.startsWith('/api/v1/') || visited.has(next)) throw Error('Unapproved pagination.');
            // Pagination may alter only page/cursor, never course or endpoint.
            if (url.pathname !== new URL(routes[skill], approvedOrigin).pathname || url.searchParams.get('context_codes[]') !== new URL(routes[skill], approvedOrigin).searchParams.get('context_codes[]')) throw Error('Pagination scope changed.');
            visited.add(next);
            const response = await fetch(next, {credentials: 'same-origin', method: 'GET', redirect: 'error'});
            if (response.status === 401 || response.status === 403) return {items, complete: false, status: 'login_required', checkpoint: next};
            if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) return {items, complete: false, status: 'unsupported_layout', checkpoint: next};
            const body = await response.json();
            items.push(...(Array.isArray(body) ? body : [body]).map(item => ({...item, canvasStudentId:String(student.user_id), locator: `${approvedOrigin}/courses/${course}/${skill === 'assignments' ? 'assignments/'+item.id : ''}`})));
            const link = response.headers.get('link') || '';
            next = link.match(/<([^>]+)>;\s*rel="next"/)?.[1] || null;
          }
          return {items, complete: !next, status: next ? 'partial' : 'completed', checkpoint: next};
        }});
        const data = result[0]?.result;
        if (!data) throw Error('Canvas returned no supported read result.');
        for (let offset = 0; offset < Math.max(1, data.items.length); offset += 200) {
          const response = await fetch(`${config.backend}/v1/canvas/connections/${config.connectionId}/sync`, {method: 'POST', headers: {'Content-Type': 'application/json', ...(config.authToken ? {Authorization: `Bearer ${config.authToken}`} : {}), ...(config.desktopToken ? {'X-Forma-Desktop-Token': config.desktopToken} : {})}, body: JSON.stringify({grant: config.grant, deviceId: config.deviceId, origin: config.origin, courseId, externalCourseId, skill, ...data, complete: data.complete && offset+200 >= data.items.length, items: data.items.slice(offset, offset+200)})});
          if (!response.ok) throw Error(`Open Learn import failed (${response.status}). Renew the connection or session.`);
        }
        if (data.status === 'login_required') throw Error('Sign in to Canvas and retry. Earlier imported work is preserved.');
      }
    }
    status.textContent = 'Read completed. Review imports and uncertain facts in Open Learn.';
  } catch (error) { status.textContent = error.message; }
};
document.querySelector('#disconnect').onclick = async () => {
  const {companionConnections=[]}=await chrome.storage.local.get('companionConnections');
  if (companionConnections.length) {await chrome.runtime.sendMessage({type:'companion-disconnect'});status.textContent='Browser companion disconnected.';return;}
  const {config} = await chrome.storage.session.get('config');
  if (config) {
    const response = await fetch(`${config.backend}/v1/canvas/connections/${config.connectionId}`, {method: 'DELETE', headers: config.authToken ? {Authorization: `Bearer ${config.authToken}`} : {}});
    if (!response.ok) { status.textContent = 'Server disconnect failed. Revoke the connection in Open Learn.'; return; }
    await chrome.permissions.remove({origins: [config.origin+'/*']});
  }
  await chrome.storage.session.remove('config'); status.textContent = 'Disconnected.';
};
