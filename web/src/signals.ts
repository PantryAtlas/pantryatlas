/**
 * PantryAtlas Navigator — Preact Signals state
 * Single source of truth for mode, pantry, and UI state.
 */
import { signal, computed } from '@preact/signals'
import type { RankedRecipe } from './components/RecipeCard'
import { enqueueMutation, replayQueue } from './lib/offline-queue'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type Mode = 'home' | 'community'

export interface PantryItem {
  canonical_name: string
  raw_text: string
  quantity?: { amount: number; unit: string }
  expires_at?: string
  /** present | low | used_up — coarse confidence in on-hand presence */
  state?: 'present' | 'low' | 'used_up'
  confidence?: number
  last_observed_at?: string
  source?: string
  /** Present on optimistically-added items awaiting sync. */
  _pending?: boolean
}

export interface CookEvent {
  id: number
  recipe_id?: string | null
  dish_name: string
  servings?: number | null
  cooked_at: string
  rating?: number | null
  notes?: string | null
  consumed: { canonical_name: string; coarse_amount: string }[]
  source: string
}

export type AddState = 'idle' | 'resolving' | 'resolved' | 'error'

// ---------------------------------------------------------------------------
// Mode — persisted to localStorage
// ---------------------------------------------------------------------------

function loadMode(): Mode {
  try {
    const saved = localStorage.getItem('pantryatlas.mode')
    if (saved === 'home' || saved === 'community') return saved
  } catch {
    // localStorage unavailable (e.g., private browsing restriction)
  }
  return 'home'
}

export const mode = signal<Mode>(loadMode())

// Returns true if mode has never been set (first launch)
export function hasPersistedMode(): boolean {
  try {
    return localStorage.getItem('pantryatlas.mode') !== null
  } catch {
    return false
  }
}

export function setMode(m: Mode) {
  mode.value = m
  try {
    localStorage.setItem('pantryatlas.mode', m)
  } catch {
    // ignore
  }
}

// ---------------------------------------------------------------------------
// Mode switcher sheet visibility
// ---------------------------------------------------------------------------

// Open on first launch (no persisted mode), or on mode chip tap.
// Starts as false; Navigator.tsx sets this to true on mount if no persisted mode.
export const modeSwitcherOpen = signal<boolean>(false)

// ---------------------------------------------------------------------------
// Pantry
// ---------------------------------------------------------------------------

export const pantry = signal<PantryItem[]>([])

export async function fetchPantry() {
  try {
    const res = await fetch('/navigator/pantry')
    if (res.ok) {
      pantry.value = await res.json()
    }
  } catch {
    // network error — keep existing pantry
  }
}

/**
 * Add a pantry item via text input.
 * - Online: POST to backend, then re-fetch.
 * - Offline: enqueue the mutation + optimistically add with _pending flag.
 */
export async function addItem(rawText: string): Promise<{ ok: boolean; status?: number }> {
  if (!navigator.onLine) {
    // Offline path: enqueue + optimistic update
    await enqueueMutation('add', { raw_text: rawText })
    // Optimistic local pantry insert (canonical_name = raw for now; replaced on sync)
    const optimistic: PantryItem = {
      canonical_name: rawText.trim().toLowerCase(),
      raw_text: rawText,
      _pending: true,
    }
    pantry.value = [...pantry.value.filter(i => i.canonical_name !== optimistic.canonical_name), optimistic]
    return { ok: true }
  }

  // Online path
  const res = await fetch('/navigator/pantry/items', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ raw_text: rawText }),
  })
  if (res.ok || res.status === 201) {
    await fetchPantry()
  }
  return { ok: res.ok || res.status === 201, status: res.status }
}

/**
 * Delete a pantry item.
 * - Online: DELETE to backend, then re-fetch.
 * - Offline: enqueue the mutation + optimistically remove from local list.
 */
export async function deleteItem(canonicalName: string) {
  if (!navigator.onLine) {
    // Offline path: enqueue + optimistic removal
    await enqueueMutation('delete', { canonical_name: canonicalName })
    pantry.value = pantry.value.filter(i => i.canonical_name !== canonicalName)
    return
  }

  // Online path
  try {
    await fetch(`/navigator/pantry/items/${encodeURIComponent(canonicalName)}`, {
      method: 'DELETE',
    })
    await fetchPantry()
  } catch {
    // ignore
  }
}

// ---------------------------------------------------------------------------
// Meals / cook events
// ---------------------------------------------------------------------------

export const meals = signal<CookEvent[]>([])

export async function fetchMeals() {
  try {
    const res = await fetch('/navigator/meals')
    if (res.ok) meals.value = await res.json()
  } catch {
    // keep existing
  }
}

/** Mark a recipe cooked: logs it + soft-decrements its ingredients, then refreshes. */
export async function cookRecipe(opts: {
  recipe_id?: string
  dish_name: string
  servings?: number
  consumed?: { canonical_name: string; coarse_amount: string }[]
}): Promise<boolean> {
  try {
    const res = await fetch('/navigator/cook', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(opts),
    })
    if (res.ok || res.status === 201) {
      await fetchPantry()
      await fetchMeals()
      return true
    }
  } catch {
    // ignore
  }
  return false
}

/** Coarse consume on a pantry item: 'half' | 'used_up' | 'discarded'. */
export async function consumeItem(canonicalName: string, coarseAmount: string) {
  try {
    const res = await fetch(`/navigator/pantry/items/${encodeURIComponent(canonicalName)}/consume`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ coarse_amount: coarseAmount }),
    })
    if (res.ok) await fetchPantry()
  } catch {
    // ignore
  }
}

export async function restoreItem(canonicalName: string) {
  try {
    const res = await fetch(`/navigator/pantry/items/${encodeURIComponent(canonicalName)}/restore`, {
      method: 'POST',
    })
    if (res.ok) await fetchPantry()
  } catch {
    // ignore
  }
}

// ---------------------------------------------------------------------------
// Reconnect replay — wired up in main.tsx via wireOfflineReplay()
// ---------------------------------------------------------------------------

let _replayScheduled = false

/**
 * Call once at app init. Listens for 'online' events and replays any
 * pending offline mutations, then refreshes pantry from server.
 */
export function wireOfflineReplay() {
  if (_replayScheduled) return
  _replayScheduled = true

  window.addEventListener('online', async () => {
    try {
      const count = await replayQueue()
      if (count > 0) {
        // Clear _pending flags by re-fetching authoritative pantry state
        await fetchPantry()
      }
    } catch {
      // best-effort replay
    }
  })
}

// ---------------------------------------------------------------------------
// Add-ingredient input state
// ---------------------------------------------------------------------------

export const addInputValue = signal<string>('')
export const addState = signal<AddState>('idle')
export const addResolvedName = signal<string>('')
export const addErrorMsg = signal<string>('')

// ---------------------------------------------------------------------------
// Photo review sheet
// ---------------------------------------------------------------------------

export const photoSheetOpen = signal<boolean>(false)
export const photoFile = signal<File | null>(null)
export const photoSheetState = signal<'loading' | 'parsed' | 'error' | 'unavailable'>('loading')
export const photoDetectedItems = signal<{ label: string; checked: boolean }[]>([])
export const photoErrorMsg = signal<string>('')

// ---------------------------------------------------------------------------
// Computed helpers
// ---------------------------------------------------------------------------

export const pantryCount = computed(() => pantry.value.length)

export const expiringSoon = computed(() =>
  pantry.value.filter((i) => {
    if (i.state === 'used_up') return false
    const d = daysUntilExpiry(i.expires_at)
    return d !== null && d >= 0 && d <= 3
  })
)

export const modeLabel = computed(() =>
  mode.value === 'home' ? 'Home Kitchen' : 'Community Kitchen'
)

export const modeIcon = computed(() =>
  mode.value === 'home' ? '🏠' : '🍲'
)

export const recipeSectionLabel = computed(() =>
  mode.value === 'home'
    ? 'Recipes you can cook tonight'
    : 'Recipes you can scale to 50–500 meals'
)

// ---------------------------------------------------------------------------
// Recipe results state
// ---------------------------------------------------------------------------

export type RecipeLoadState = 'idle' | 'loading' | 'done'

// Phase 2 of the instant-then-refine flow: the live re-ordering pass.
//  idle     — no refine in flight (e.g. no results yet)
//  refining — /refine in flight; cards still show coverage order
//  refined  — refine applied; ordering has settled with real substitution
//  offline  — refine unavailable (offline / error); coverage order stands
export type RefineState = 'idle' | 'refining' | 'refined' | 'offline'

export const recipes = signal<RankedRecipe[]>([])
export const recipeLoadState = signal<RecipeLoadState>('idle')
export const refineState = signal<RefineState>('idle')

/** Stable identity for a ranked recipe — used for keys and the swaps cache. */
export function recipeKey(r: RankedRecipe): string {
  return r.recipe.title + '|' + r.recipe.ingredients.join(',')
}

// In-flight refine controller; aborted when the pantry changes mid-refine.
let _refineAbort: AbortController | null = null

export async function fetchRecipes(pantryItems: PantryItem[], currentMode: Mode) {
  // A new pantry invalidates any in-flight refine and all cached/in-flight swaps
  // (a swap resolving after this point would be against the stale pantry).
  _refineAbort?.abort()
  _refineAbort = null
  for (const c of _swapAborts.values()) c.abort()
  _swapAborts.clear()
  recipeSwaps.value = {}
  refineState.value = 'idle'
  recipeLoadState.value = 'loading'
  try {
    const res = await fetch('/navigator/recipes/from-pantry', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mode: currentMode,
        pantry: pantryItems.map((it) => it.canonical_name),
      }),
    })
    if (res.ok) {
      const instant: RankedRecipe[] = await res.json()
      recipes.value = instant
      recipeLoadState.value = 'done'
      // Phase 2: settle the ordering with real substitution scores.
      if (instant.length > 0) void refineRecipes(instant, currentMode)
    } else {
      recipes.value = []
      recipeLoadState.value = 'done'
    }
  } catch {
    recipes.value = []
    recipeLoadState.value = 'done'
  }
}

/**
 * Refine the instant (coverage-ranked) results with real substitution scores.
 * Sends the painted recipes back to the server, which re-ranks them. Because
 * fast mode was optimistic, refining can only lower scores — cards converge
 * downward into a stable settle.
 */
async function refineRecipes(instant: RankedRecipe[], currentMode: Mode) {
  if (!navigator.onLine) {
    refineState.value = 'offline'
    return
  }
  const controller = new AbortController()
  _refineAbort = controller
  refineState.value = 'refining'
  try {
    const res = await fetch('/navigator/recipes/from-pantry/refine', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(instant.map((r) => r.recipe)),
      signal: controller.signal,
    })
    if (controller.signal.aborted || _refineAbort !== controller) return
    if (res.ok) {
      recipes.value = await res.json()
      refineState.value = 'refined'
    } else {
      // Server hiccup — keep coverage order, mark settled so the chip clears.
      refineState.value = 'refined'
    }
  } catch (err) {
    if ((err as Error)?.name === 'AbortError') return // superseded by a newer pantry
    refineState.value = 'offline'
  }
}

// ---------------------------------------------------------------------------
// Smart swaps — lazy per-recipe substitution suggestions, fetched on expand
// ---------------------------------------------------------------------------

export interface SwapSuggestion {
  missing: string
  best_swap: string | null
  similarity: number
  reason: string | null
}

export interface SwapEntry {
  state: 'loading' | 'done' | 'offline' | 'error'
  swaps?: SwapSuggestion[]
}

// Keyed by recipeKey(); cleared whenever the pantry changes (see fetchRecipes).
export const recipeSwaps = signal<Record<string, SwapEntry>>({})

const _swapAborts = new Map<string, AbortController>()

/**
 * Fetch swap suggestions for one recipe's missing ingredients. Idempotent per
 * recipe key while a result is cached; embeds only this recipe's missing items
 * server-side, so it is fast. No-op offline (renders "unavailable offline").
 */
export async function fetchSwaps(r: RankedRecipe) {
  const key = recipeKey(r)
  const existing = recipeSwaps.value[key]
  if (existing && existing.state !== 'error') return // already loading/done/offline

  if (!navigator.onLine) {
    recipeSwaps.value = { ...recipeSwaps.value, [key]: { state: 'offline' } }
    return
  }

  _swapAborts.get(key)?.abort()
  const controller = new AbortController()
  _swapAborts.set(key, controller)
  recipeSwaps.value = { ...recipeSwaps.value, [key]: { state: 'loading' } }

  try {
    const res = await fetch('/navigator/recipes/swaps', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ingredients: r.recipe.ingredients }),
      signal: controller.signal,
    })
    if (controller.signal.aborted) return
    if (res.ok) {
      const data = await res.json()
      recipeSwaps.value = {
        ...recipeSwaps.value,
        [key]: { state: 'done', swaps: data.swaps as SwapSuggestion[] },
      }
    } else {
      recipeSwaps.value = { ...recipeSwaps.value, [key]: { state: 'error' } }
    }
  } catch (err) {
    if ((err as Error)?.name === 'AbortError') return
    recipeSwaps.value = { ...recipeSwaps.value, [key]: { state: 'offline' } }
  }
}

// ---------------------------------------------------------------------------
// Expiry helpers
// Parse ISO date string (YYYY-MM-DD) as local date to avoid UTC midnight shift.
function parseLocalDate(iso: string): Date {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d) // local midnight
}

export function daysUntilExpiry(expiresAt: string | undefined): number | null {
  if (!expiresAt) return null
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const exp = parseLocalDate(expiresAt)
  return Math.round((exp.getTime() - today.getTime()) / 86_400_000)
}
