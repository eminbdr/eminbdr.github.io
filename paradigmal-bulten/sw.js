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
  // Completely ignore requests with unsupported schemes (like chrome-extension://)
  if (!event.request.url.startsWith('http')) {
    return;
  }
});