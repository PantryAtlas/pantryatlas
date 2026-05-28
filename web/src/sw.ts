// PantryAtlas Navigator — Service Worker
// TypeScript config: tsconfig.sw.json (lib: ["ES2020", "WebWorker"])
// eslint-disable-next-line no-var
export {}; // Make this a module to avoid global scope conflicts
// Re-declare self with the correct type for ServiceWorkerGlobalScope
declare const self: ServiceWorkerGlobalScope & typeof globalThis;
// Strategy rationale:
//   - Precache: app shell (index.html + hashed JS/CSS) at install time.
//     These are immutable-by-hash so cache-first is safe.
//   - Runtime navigator API GETs (/navigator/recipes/from-pantry,
//     /navigator/pantry): stale-while-revalidate — instant load from
//     cache on repeat visits, background fetch keeps data fresh.
//     Chosen over network-first because pantry data doesn't change
//     second-by-second; stale results are still useful offline.

const SHELL_CACHE = 'pantryatlas-shell-v1';
const API_CACHE = 'pantryatlas-api-v1';

// App shell assets to precache at install.
// NOTE: hashed JS/CSS filenames are injected at build time only in the
// vite-plugin-pwa injectManifest flow. Since we're using hand-rolled
// rollup input, we precache the known stable paths; hashed assets are
// runtime-cached on first fetch.
const SHELL_ASSETS = ['/', '/index.html'];

// Navigator API paths to runtime-cache (stale-while-revalidate)
const API_PATHS = ['/navigator/recipes/from-pantry', '/navigator/pantry'];

self.addEventListener('install', (event: ExtendableEvent) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) => cache.addAll(SHELL_ASSETS))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event: ExtendableEvent) => {
  // Remove old shell caches that don't match current version
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((k) => k.startsWith('pantryatlas-') && k !== SHELL_CACHE && k !== API_CACHE)
            .map((k) => caches.delete(k)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event: FetchEvent) => {
  const { request } = event;
  const url = new URL(request.url);

  // Only handle GET requests for same-origin
  if (request.method !== 'GET' || url.origin !== self.location.origin) {
    return;
  }

  const pathname = url.pathname;

  // Navigator API: stale-while-revalidate
  if (API_PATHS.some((p) => pathname.startsWith(p))) {
    event.respondWith(staleWhileRevalidate(API_CACHE, request));
    return;
  }

  // App shell (HTML navigation requests) and hashed static assets:
  // cache-first with network fallback
  if (pathname === '/' || pathname.endsWith('.html')) {
    event.respondWith(cacheFirstWithNetworkFallback(SHELL_CACHE, request));
    return;
  }

  // JS/CSS/font assets (hashed filenames → immutable): cache-first,
  // store on first fetch so subsequent loads are instant
  if (
    pathname.startsWith('/assets/') ||
    pathname.startsWith('/fonts/') ||
    pathname.startsWith('/icons/')
  ) {
    event.respondWith(cacheFirstWithNetworkFallback(SHELL_CACHE, request));
    return;
  }
});

async function staleWhileRevalidate(cacheName: string, request: Request): Promise<Response> {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);

  const networkFetch = fetch(request)
    .then((response) => {
      if (response.ok) {
        cache.put(request, response.clone());
      }
      return response;
    })
    .catch(() => null);

  // Return cached immediately; network revalidates in background
  return cached ?? (await networkFetch) ?? new Response('Offline', { status: 503 });
}

async function cacheFirstWithNetworkFallback(
  cacheName: string,
  request: Request,
): Promise<Response> {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  if (cached) return cached;

  try {
    const response = await fetch(request);
    if (response.ok) {
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    return new Response('Offline', { status: 503 });
  }
}
