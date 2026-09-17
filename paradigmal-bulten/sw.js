const CACHE_NAME = 'paradigma-cache-v1';

// Install event: cache the main UI shell
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll([
        './',
        './index.html',
        './manifest.json'
      ]);
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

// Fetch event: Network-first, fallback to cache
self.addEventListener('fetch', (event) => {
  event.respondWith(
    fetch(event.request)
      .then((networkResponse) => {
        // Clone the response and save it to cache for future offline use
        const responseClone = networkResponse.clone();
        caches.open(CACHE_NAME).then((cache) => {
          // Only cache GET requests
          if (event.request.method === 'GET') {
            cache.put(event.request, responseClone);
          }
        });
        return networkResponse;
      })
      .catch(() => {
        // If network fails (offline), return the cached version
        return caches.match(event.request);
      })
  );
});