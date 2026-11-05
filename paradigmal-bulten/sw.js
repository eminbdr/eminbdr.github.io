// The old Bülten moved to https://bulten-worker.muhammet5244.workers.dev/.
// This replaces the old caching service worker: on the next online start of
// an installed app it deletes the offline copy, sends open windows to the new
// address and unregisters itself. It handles no requests.
const NEW_HOME = 'https://bulten-worker.muhammet5244.workers.dev/';

self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.map((k) => caches.delete(k)));
    await self.clients.claim();
    const windows = await self.clients.matchAll({ type: 'window' });
    await Promise.all(windows.map((w) => w.navigate(NEW_HOME).catch(() => {})));
    await self.registration.unregister();
  })());
});
