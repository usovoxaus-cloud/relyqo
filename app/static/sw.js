// Never replay authenticated documents from an offline cache.
self.addEventListener('install', event => event.waitUntil(self.skipWaiting()));
self.addEventListener('activate', event => event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith('relyqo-')).map(key => caches.delete(key)))).then(() => self.clients.claim())));
self.addEventListener('fetch', event => {
  if (event.request.mode !== 'navigate' || event.request.method !== 'GET') return;
  event.respondWith(fetch(event.request).catch(() => new Response('<!doctype html><html lang="ru"><meta name="viewport" content="width=device-width,initial-scale=1"><title>RELYQO</title><body style="background:#081923;color:#eef8f6;font:18px system-ui;padding:28px"><h1>RELYQO</h1><p>Нет соединения. Проверьте интернет и обновите страницу.</p><p lang="uz">Internet aloqasi yo‘q. Ulanishni tekshiring va sahifani yangilang.</p></body></html>', {status:503,headers:{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'}})));
});
