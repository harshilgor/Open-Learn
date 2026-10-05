async function openLearnCanvasRead(args) {
  if (location.origin !== args.origin || new URL(args.url).origin !== args.origin || !new URL(args.url).pathname.startsWith('/api/v1/')) throw Error('origin_not_approved');
  const profile = await fetch(args.origin + '/api/v1/users/self/profile', {credentials: 'same-origin', redirect: 'error'});
  if (!profile.ok) return {url: args.url, documentRevision: 'login', status: 'login_required', blocks: [], controls: []};
  const account = await profile.json();
  const response = await fetch(args.url, {credentials: 'same-origin', redirect: 'error'});
  if ([401,403].includes(response.status)) return {url: args.url, documentRevision: 'login', status: 'login_required', blocks: [], controls: []};
  if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) return {url: args.url, documentRevision: 'unsupported', status: 'unsupported', blocks: [], controls: []};
  const raw = await response.text();
  if (raw.length > 1500000) throw Error('unsupported_file');
  const body = JSON.parse(raw), items = Array.isArray(body) ? body : [body];
  const links = [], blocks = [];
  items.slice(0, 100).forEach((item,n) => {
    const fragment = new DOMParser().parseFromString(String(item.syllabus_body || item.message || item.description || ''), 'text/html');
    fragment.querySelectorAll('script,style').forEach(el=>el.remove());
    const description = fragment.body.textContent || '';
    const text = [item.name || item.title || 'Course information', description,
      item.due_at ? 'Due: '+item.due_at : '', item.start_at ? 'Start: '+item.start_at : '', item.end_at ? 'End: '+item.end_at : ''].filter(Boolean).join('\n').slice(0, 20000);
    blocks.push({ref:'item:'+n,text});
    fragment.querySelectorAll('a[href]').forEach(a => {
      const href = new URL(a.getAttribute('href'), args.origin).href;
      if (href.startsWith('https:') && links.length < 200) links.push({ref:'e'+links.length,role:'link',name:(a.textContent || 'Course document').slice(0,300),href,writable:false});
    });
    for (const entry of item.items || []) {
      const href = entry.html_url || entry.external_url;
      if (href?.startsWith('https:') && links.length < 200) links.push({ref:'e'+links.length,role:'link',name:String(entry.title || 'Module item').slice(0,300),href,writable:false});
    }
  });
  let hash = 2166136261; for (const char of raw) { hash ^= char.charCodeAt(0); hash = Math.imul(hash,16777619); }
  const next = (response.headers.get('link') || '').match(/<([^>]+)>;\s*rel="next"/)?.[1] || null;
  return {url:args.url,title:'Canvas course data',documentRevision:(hash>>>0).toString(16),blocks,controls:links,
    platformItems: items.slice(0,100).map(item => ({id:item.id,name:item.name,title:item.title,due_at:item.due_at,start_at:item.start_at,end_at:item.end_at,
      location_name:item.location_name,enrollments:item.enrollments,term:item.term,workflow_state:item.workflow_state})),
    accountId:String(account.id),nextCursor:next,complete:!next && items.length<=100,status:next?'partial':'completed',truncated:items.length>100};
}
