/* Service Worker:離線外殼 + 靜態資源快取。
   Gradio 的 API / 佇列 / 檔案下載一律走網路,不攔截。 */
const VERSION = "v1";
const CACHE = `csv-viewer-${VERSION}`;
const PRECACHE = [
  "/offline.html",
  "/manifest.webmanifest",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/icons/icon.svg",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // 頁面導覽:網路優先,離線時顯示離線頁
  if (req.mode === "navigate") {
    event.respondWith(fetch(req).catch(() => caches.match("/offline.html")));
    return;
  }

  // 自家靜態資源(圖示、manifest、離線頁):先回快取,背景更新
  if (url.pathname.startsWith("/static/") || url.pathname === "/manifest.webmanifest" || url.pathname === "/offline.html") {
    event.respondWith(
      caches.match(req).then((hit) => {
        const refresh = fetch(req).then((res) => {
          if (res && res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); }
          return res;
        }).catch(() => hit);
        return hit || refresh;
      })
    );
  }
  // 其餘(/gradio_api、/queue、/file 等)交給瀏覽器預設處理
});
