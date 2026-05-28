/**
 * PantryAtlas Navigator — Preact Signals state
 * Single source of truth for mode, pantry, and UI state.
 */
import { signal, computed } from '@preact/signals'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type Mode = 'home' | 'community'

export interface PantryItem {
  canonical_name: string
  raw_text: string
  quantity?: { amount: number; unit: string }
  expires_at?: string // ISO date string or null
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

export async function deleteItem(canonicalName: string) {
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
