self.addEventListener('push', event => {
  let data; try {data=event.data.json();}catch{return;}
  event.waitUntil(self.registration.showNotification(data.title || 'OpenLearn reminder', {
    body:data.body || 'An academic event is approaching.', tag:'openlearn-'+data.id,
    data:{url:typeof data.url==='string'&&data.url.startsWith('/chat?')?data.url:'/'}, renotify:false
  }));
});
self.addEventListener('notificationclick',event=>{
  event.notification.close();
  const path=event.notification.data?.url;
  event.waitUntil(self.clients.openWindow(new URL(typeof path==='string'&&path.startsWith('/chat?')?path:'/',self.location.origin).href));
});
self.addEventListener('activate',event=>event.waitUntil(self.clients.claim()));
