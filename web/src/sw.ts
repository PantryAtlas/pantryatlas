// PantryAtlas Navigator — Service Worker
// TypeScript config: tsconfig.sw.json (lib: ["ES2020", "WebWorker"])
// eslint-disable-next-line no-var
export {}; // Make this a module to avoid global scope conflicts
// Re-declare self with the correct type for ServiceWorkerGlobalScope
declare const self: ServiceWorkerGlobalScope & typeof globalThis;

// ---------------------------------------------------------------------------
// Cache names
// ---------------------------------------------------------------------------
const SHELL_CACHE = 'pantryatlas-shell-v1';
const RECIPES_CACHE = 'pantryatlas-recipes-v1'; // stale-while-revalidate, capped at 20
const PANTRY_CACHE = 'pantryatlas-pantry-v1';   // network-first

// Max recipe-results cache entries (evict oldest when exceeded)
const RECIPES_CACHE_MAX = 20;

// App shell assets to precache at install.
// NOTE: hashed JS/CSS filenames are injected at build time only in the
// vite-plugin-pwa injectManifest flow. Since we're using hand-rolled
// rollup input, we precache the known stable paths; hashed assets are
// runtime-cached on first fetch.
const SHELL_ASSETS = ['/', '/index.html'];

// ---------------------------------------------------------------------------
// Install: precache app shell (cache-first)
// ---------------------------------------------------------------------------
self.addEventListener('install', (event: ExtendableEvent) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) => cache.addAll(SHELL_ASSETS))
      .then(() => self.skipWaiting()),
  );
});

// ---------------------------------------------------------------------------
// Activate: prune old caches
// ---------------------------------------------------------------------------
self.addEventListener('activate', (event: ExtendableEvent) => {
  const CURRENT_CACHES = new Set([SHELL_CACHE, RECIPES_CACHE, PANTRY_CACHE]);
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((k) => k.startsWith('pantryatlas-') && !CURRENT_CACHES.has(k))
            .map((k) => caches.delete(k)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

// ---------------------------------------------------------------------------
// Message: support 'enforce_recipe_cap' for testing
// ---------------------------------------------------------------------------
self.addEventListener('message', (event: ExtendableMessageEvent) => {
  if (event.data && event.data.type === 'enforce_recipe_cap') {
    event.waitUntil(
      enforceRecipesCap().then(() => {
        if (event.ports && event.ports[0]) {
          event.ports[0].postMessage({ done: true });
        }
      }),
    );
  }
});

// ---------------------------------------------------------------------------
// Fetch: three explicit routing strategies
// ---------------------------------------------------------------------------
self.addEventListener('fetch', (event: FetchEvent) => {
  const { request } = event;
  const url = new URL(request.url);

  // Limit to same-origin only
  if (url.origin !== self.location.origin) {
    return;
  }

  const pathname = url.pathname;

  // ── Strategy 1: stale-while-revalidate — /navigator/recipes/from-pantry ──
  // Only the INSTANT coverage-ranked call is cached (exact path match). The
  // refine and swaps calls are deliberately NetworkOnly: they are live,
  // pantry-dependent enrichments that must never serve a stale result. They
  // fall through to the default (no respondWith) below → straight to network,
  // and degrade gracefully offline (the signals layer marks them offline).
  // POST bodies can't be cached by the Cache API directly, so we key on a
  // synthetic GET derived from the URL + body. Capped at RECIPES_CACHE_MAX.
  if (pathname === '/navigator/recipes/from-pantry') {
    if (request.method === 'POST') {
      event.respondWith(staleWhileRevalidateRecipes(request));
      return;
    }
    // Ignore other methods for this path
    return;
  }

  // Network-only (no caching) for the live enrichment endpoints.
  if (
    pathname === '/navigator/recipes/from-pantry/refine' ||
    pathname === '/navigator/recipes/swaps'
  ) {
    return; // no respondWith → browser handles via network
  }

  // Only handle GET from here on
  if (request.method !== 'GET') {
    return;
  }

  // ── Strategy 2: network-first — /navigator/pantry GET ──
  if (pathname.startsWith('/navigator/pantry')) {
    event.respondWith(networkFirst(PANTRY_CACHE, request));
    return;
  }

  // ── Strategy 3: cache-first — app shell (HTML navigation + hashed assets) ──
  if (
    pathname === '/' ||
    pathname.endsWith('.html') ||
    pathname.startsWith('/assets/') ||
    pathname.startsWith('/fonts/') ||
    pathname.startsWith('/icons/')
  ) {
    event.respondWith(cacheFirst(SHELL_CACHE, request));
    return;
  }
});

// ---------------------------------------------------------------------------
// Strategy implementations
// ---------------------------------------------------------------------------

/**
 * stale-while-revalidate: return cache immediately while revalidating in
 * background. Used for /navigator/recipes/from-pantry (POST).
 *
 * Because POST bodies can't be cached by the Cache API directly, we
 * consume the request body and build a synthetic GET key:
 *   synthetic URL = original URL + '?_body=' + base64(body)
 * This lets cache.match/put work on the cloned request.
 * Cache is capped at RECIPES_CACHE_MAX; oldest entry evicted on overflow.
 */
async function staleWhileRevalidateRecipes(request: Request): Promise<Response> {
  const cache = await caches.open(RECIPES_CACHE);

  // Build a synthetic cache key (GET with body encoded in URL)
  const bodyText = await request.clone().text();
  const syntheticKey = new Request(
    request.url + '?_body=' + encodeURIComponent(bodyText),
    { method: 'GET' },
  );

  const cached = await cache.match(syntheticKey);

  // Network fetch (original request — body is still intact on the clone)
  const networkFetch = fetch(request.clone())
    .then(async (response) => {
      if (response.ok) {
        await cache.put(syntheticKey, response.clone());
        await enforceRecipesCap();
      }
      return response;
    })
    .catch(() => null as Response | null);

  // Return cached immediately; network revalidates in background
  return cached ?? (await networkFetch) ?? new Response('Offline', { status: 503 });
}

/**
 * network-first: try network; fall back to cache when offline.
 * Used for /navigator/pantry GET.
 */
async function networkFirst(cacheName: string, request: Request): Promise<Response> {
  const cache = await caches.open(cacheName);
  try {
    const response = await fetch(request.clone());
    if (response.ok) {
      cache.put(request, response.clone()); // background write
    }
    return response;
  } catch {
    // Network failed — fall back to cache
    const cached = await cache.match(request);
    return cached ?? new Response('Offline', { status: 503 });
  }
}

/**
 * cache-first: serve from cache; fetch and store on cache miss.
 * Used for app shell (index.html, hashed JS/CSS, fonts, icons).
 */
async function cacheFirst(cacheName: string, request: Request): Promise<Response> {
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

// ---------------------------------------------------------------------------
// Cap enforcement: keep RECIPES_CACHE_MAX most-recent entries
// (cache.keys() returns insertion order — evict from the front)
// ---------------------------------------------------------------------------
async function enforceRecipesCap(): Promise<void> {
  const cache = await caches.open(RECIPES_CACHE);
  const keys = await cache.keys();
  const excess = keys.length - RECIPES_CACHE_MAX;
  if (excess > 0) {
    // Delete oldest entries (front of the list)
    await Promise.all(keys.slice(0, excess).map((k) => cache.delete(k)));
  }
}
