/* Service Worker stub — installs immediately, no caching strategy yet */
const CACHE_NAME = "faktury-v1";

self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  /* Pass-through: no offline caching yet */
  event.respondWith(fetch(event.request));
});
