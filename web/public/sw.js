// Lifter service worker: makes the app installable, and caches nothing.
// The app shows live data (read through /api on the same origin): a cache would keep health data
// in the phone's storage and could serve an old version of the app when the network or the
// login fails. On activation it deletes the caches an earlier version left behind.
self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

// Every request goes to the network, as if there were no service worker.
self.addEventListener("fetch", () => {});
