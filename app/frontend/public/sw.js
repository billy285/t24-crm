const CACHE_PREFIX = 't24-os-offline-';
const CACHE_NAME = `${CACHE_PREFIX}v1`;
const OFFLINE_URL = '/offline.html';

const neverHandleNavigation = (url) => (
  url.origin !== self.location.origin
  || url.pathname.startsWith('/api/')
  || url.pathname.startsWith('/auth/')
  || url.pathname.startsWith('/logout')
  || /(?:export|download|\.csv$|\.xlsx$|\.pdf$)/i.test(url.pathname)
);

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.add(new Request(OFFLINE_URL, { cache: 'reload' }))),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys
          .filter((key) => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME)
          .map((key) => caches.delete(key)),
      ))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET' || request.mode !== 'navigate') return;

  const url = new URL(request.url);
  if (neverHandleNavigation(url)) return;

  event.respondWith(
    fetch(new Request(request, { cache: 'no-store' }))
      .catch(async () => {
        const offline = await caches.match(OFFLINE_URL, { ignoreSearch: true });
        return offline || new Response('需要网络连接', {
          status: 503,
          headers: { 'Content-Type': 'text/plain; charset=utf-8' },
        });
      }),
  );
});
