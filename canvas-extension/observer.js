/* Packaged observation code shared by the companion and Playwright executor. */
function openLearnObserve(query) {
  if (document.querySelector('input[type="password"],input[autocomplete="one-time-code"],input[autocomplete="current-password"],input[autocomplete="new-password"]')) {
    return {url:location.href,title:'',documentRevision:'private-login',tabId:'',blocks:[],controls:[],status:'login_required',complete:false,truncated:false};
  }
  const needle = typeof query === 'string' ? query.toLowerCase() : '';
  const visible = el => {
    const box = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return box.width > 0 && box.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
  };
  const clean = value => String(value || '').replace(/\s+/g, ' ').trim();
  const excluded = 'script,style,noscript,nav[aria-label="account"],input[type="password"],input[autocomplete="one-time-code"]';
  const main = document.querySelector('main,[role="main"]') || document.body;
  const elements = Array.from(main.querySelectorAll('h1,h2,h3,h4,p,li,td,th,pre,blockquote,article,section'));
  const blocks = [];
  let characters = 0;
  for (const el of elements) {
    if (!visible(el) || el.closest(excluded)) continue;
    if (el.matches('article,section') && el.querySelector('p,li,td')) continue;
    let text = clean(el.innerText);
    if (needle) {const index=text.toLowerCase().indexOf(needle);if(index<0)continue;text=text.slice(Math.max(0,index-2000),index+8000);}
    if (!text || text.length < 3 || blocks.some(b => b.text === text)) continue;
    if (characters + text.length > 60000 || blocks.length >= 100) break;
    blocks.push({ref: `b${blocks.length}`, text: text.slice(0, 20000)});
    characters += text.length;
  }
  if (!blocks.length) {const text=clean(main.innerText),index=needle?text.toLowerCase().indexOf(needle):0;blocks.push({ref:'b0',text:index<0?'No matching visible text.':text.slice(Math.max(0,index-2000),index+18000)});}
  const controls = [];
  const candidates = document.querySelectorAll('a[href],button,input,textarea,select,[role="button"],[role="link"],[role="searchbox"]');
  for (const el of candidates) {
    if (!visible(el) || el.closest(excluded) || controls.length >= 240) continue;
    const name = clean(el.getAttribute('aria-label') || el.innerText || el.getAttribute('placeholder') || el.getAttribute('title'));
    if (!name || /password|credit.?card|security code|one.?time|verification code/i.test(name)) continue;
    const role = el.getAttribute('role') || (el.tagName === 'A' ? 'link' : el.tagName === 'BUTTON' ? 'button' : 'input');
    // Generic reading tasks may only fill clearly identified page search fields.
    const writable = el.getAttribute('type') === 'search' || role === 'searchbox' || /search/i.test(name);
    const ref = `e${controls.length}`;
    el.setAttribute('data-openlearn-ref', ref);
    const box = el.getBoundingClientRect();
    controls.push({ref, role, name: name.slice(0, 300), href: el.href?.startsWith('https:') ? el.href.slice(0, 2048) : null,
      writable, x: box.x + box.width / 2, y: box.y + box.height / 2});
  }
  for (const el of Array.from(document.querySelectorAll('main,div,section')).filter(el => visible(el) && el.scrollHeight > el.clientHeight + 80 && /auto|scroll/.test(getComputedStyle(el).overflowY)).slice(0, 10)) {
    const ref = `e${controls.length}`; el.setAttribute('data-openlearn-ref', ref);
    controls.push({ref, role: 'scroll_container', name: clean(el.getAttribute('aria-label') || 'Scrollable content').slice(0, 300), writable: false});
  }
  const bodyText = clean(main.innerText);
  let hash = 2166136261;
  for (const char of location.href + bodyText + JSON.stringify(controls.map(c => [c.name, c.href,c.x,c.y])) + JSON.stringify(Array.from(document.querySelectorAll('[data-openlearn-ref]')).filter(el=>el.scrollHeight>el.clientHeight+80).map(el=>el.scrollTop))) {
    hash ^= char.charCodeAt(0); hash = Math.imul(hash, 16777619);
  }
  const documentRevision = `${(hash >>> 0).toString(16)}:${window.scrollY}`;
  globalThis.__openLearnRevision = documentRevision;
  const login = document.querySelector('input[type="password"]') && /log.?in|sign.?in/i.test(document.body.innerText);
  return {url: location.href, title: document.title.slice(0, 300), documentRevision, blocks, controls,
    truncated: bodyText.length > characters + 1000, complete: !needle && bodyText.length <= characters + 1000 && !controls.some(control=>control.role==='scroll_container') && controls.length<240, status: login ? 'login_required' : 'completed'};
}
