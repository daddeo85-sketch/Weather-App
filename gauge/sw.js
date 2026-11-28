const CACHE = 'gauge-v15';
const FILES = ['./', './index.html', './manifest.webmanifest', './icon-192.png', './icon-512.png', './apple-touch-icon.png', './bg.jpg', './awake.mp4'];
self.addEventListener('install', e => { e.waitUntil(caches.open(CACHE).then(c => c.addAll(FILES.map(f => new Request(f, { cache:'reload' }))))); self.skipWaiting(); });
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k.startsWith('gauge-') && k !== CACHE).map(k => caches.delete(k))))); self.clients.claim(); });
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  if (u.origin !== location.origin) return; // TomTom and fonts go straight to the network
  if (e.request.method !== 'GET') return;
  // the app page itself always comes fresh from the network; the saved copy is only for no signal
  const nav = e.request.mode === 'navigate';
  e.respondWith(fetch(e.request, { cache: nav ? 'no-store' : 'no-cache' }).then(r => { const c = r.clone(); caches.open(CACHE).then(x => x.put(e.request, c)); return r; }).catch(() => caches.match(e.request, { ignoreSearch: nav })));
});
