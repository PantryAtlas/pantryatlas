/**
 * PantryAtlas — Offline mutation queue backed by IndexedDB.
 *
 * When the browser is offline, pantry mutations (add / delete) are stored
 * locally so the UI can optimistically reflect them. On reconnect, the queue
 * is replayed against the backend in insertion order, then cleared.
 *
 * Implementation uses raw indexedDB (no idb package) to keep dist small.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type MutationOp = 'add' | 'delete';

export interface QueuedMutation {
  /** Auto-assigned by IDB (auto-increment primary key) */
  id?: number;
  op: MutationOp;
  /** For 'add': { raw_text: string }; for 'delete': { canonical_name: string } */
  payload: Record<string, string>;
  /** ISO timestamp — for debugging/ordering */
  queuedAt: string;
}

// ---------------------------------------------------------------------------
// IDB setup
// ---------------------------------------------------------------------------

const DB_NAME = 'pantryatlas-offline';
const DB_VERSION = 1;
const STORE = 'mutation_queue';

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: 'id', autoIncrement: true });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

// ---------------------------------------------------------------------------
// Queue operations
// ---------------------------------------------------------------------------

/** Append a mutation to the queue. Returns the auto-assigned id. */
export async function enqueueMutation(
  op: MutationOp,
  payload: Record<string, string>,
): Promise<number> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite');
    const store = tx.objectStore(STORE);
    const entry: QueuedMutation = { op, payload, queuedAt: new Date().toISOString() };
    const req = store.add(entry);
    req.onsuccess = () => resolve(req.result as number);
    req.onerror = () => reject(req.error);
  });
}

/** Read all queued mutations in insertion order. */
export async function readQueue(): Promise<QueuedMutation[]> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readonly');
    const store = tx.objectStore(STORE);
    const req = store.getAll();
    req.onsuccess = () => resolve(req.result as QueuedMutation[]);
    req.onerror = () => reject(req.error);
  });
}

/** Delete a single queued mutation by id. */
async function dequeueById(id: number): Promise<void> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite');
    const store = tx.objectStore(STORE);
    const req = store.delete(id);
    req.onsuccess = () => resolve();
    req.onerror = () => reject(req.error);
  });
}

/** Clear all entries (after successful full replay). */
export async function clearQueue(): Promise<void> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite');
    const store = tx.objectStore(STORE);
    const req = store.clear();
    req.onsuccess = () => resolve();
    req.onerror = () => reject(req.error);
  });
}

// ---------------------------------------------------------------------------
// Replay
// ---------------------------------------------------------------------------

/**
 * Replay all queued mutations against the backend in insertion order.
 * Each successful mutation is deleted from the queue before the next is
 * attempted, so partial replays are safe to retry.
 *
 * Resolves with the number of successfully replayed mutations.
 * Stops on the first hard network error to preserve ordering.
 */
export async function replayQueue(
  onProgress?: (remaining: number) => void,
): Promise<number> {
  const mutations = await readQueue();
  if (mutations.length === 0) return 0;

  let replayed = 0;

  for (const mutation of mutations) {
    const { id, op, payload } = mutation;
    try {
      let res: Response;
      if (op === 'add') {
        res = await fetch('/navigator/pantry/items', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ raw_text: payload.raw_text }),
        });
      } else {
        // op === 'delete'
        res = await fetch(
          `/navigator/pantry/items/${encodeURIComponent(payload.canonical_name)}`,
          { method: 'DELETE' },
        );
      }

      // 2xx or 422 (unresolvable) both count as "done" — remove from queue
      if (res.ok || res.status === 422 || res.status === 404) {
        if (id !== undefined) await dequeueById(id);
        replayed++;
        onProgress?.(mutations.length - replayed);
      } else {
        // Server error — stop replay, retry later on next 'online' event
        break;
      }
    } catch {
      // Network error — stop replay
      break;
    }
  }

  return replayed;
}
