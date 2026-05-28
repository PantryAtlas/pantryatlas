# PantryAtlas Navigator v0.2.0 — Design Brief

> A dead-simple local server for homes and community kitchens. The navigator screen is the entire app.

## Mission

**"Use what you have, not what a recipe demands."**

PantryAtlas runs on a Raspberry Pi 5 sitting on a kitchen counter or in a community-kitchen office. Open a browser on any phone or laptop on the same Wi-Fi, point it at the Pi, type what's on the shelf, get real recipes ranked by what you can actually cook tonight.

Two audiences, same product:
- **Home kitchen** — a family of four staring at a half-used squash and some wilting kale.
- **Community kitchen** — a coordinator planning 200 meals from a donation truck's worth of mixed produce.

The product asks the user to pick one mode once, then disappears into the background and adapts ranking under the hood. There is no separate "advanced mode" or "tier dashboard." The user never sees an inference confidence indicator. The pantry is a list, the recipes are a list, and the system is quiet.

## Visual language: Gemini AI principles on a terracotta base

PantryAtlas keeps its existing warm, food-grounded color identity (terracotta seed, kitchen-notebook voice) and adopts five transferable principles from Google's Gemini AI visual design language. We do **not** copy Google's brand palette (the four-color dots, the blue/red/yellow/green system) — that would fight the warm-kitchen voice.

### Principle 1: Gradients as energy, not decoration

Gradients communicate that something *intelligent is happening*. They have a sharp, opaque leading edge that diffuses into a soft tail. They appear briefly during AI work — coverage scoring, ingredient resolution, recipe ranking — then settle. They never sit static under content as a passive background flourish.

The PantryAtlas gradient palette is built from the seed:

| Token | Stops | Usage |
|---|---|---|
| `gradient-thinking` | `#B85C38` 0% → `#E89B62` 60% → `#F5DDB8` 100% | Active inference (radial, pulsing, 1.4s cycle) |
| `gradient-warmth` | `#FFF8F6` 0% → `#FCE8E4` 100% | Page backgrounds (linear, top-to-bottom, static) |
| `gradient-vessel` | `#FFDBCD` 0% → `#FFE8DB` 50% → `#F2E2A8` 100% | Coverage ring interiors, AI-result haloes (radial) |
| `gradient-ember` | `#8B3A1F` 0% → `#B85C38` 100% | Primary action surfaces (linear, 135°) |

Gradients are **always** used with intent: they mark moments where the system is thinking, generating, or revealing. A static recipe card uses flat tonal fill — only the active card or the moment-of-result gets a gradient wash.

### Principle 2: Circles as foundational vessels

Round shapes carry the spec. The coverage ring, the input pill, the FAB, ingredient bullets, the empty-state illustrations — all built from circles. Circles "concentrate and expand energy" (Gemini's framing) and read as warm, hand-drawn, kitchen-friendly.

Card corner radii increase from the prior Material 3 baseline:

| Element | Radius | Note |
|---|---|---|
| Cards | 32px | Up from 28px — softer, more vessel-like |
| Input field | full (pill) | No square corners on text input |
| Buttons | full (pill) | All buttons are pill-shaped |
| Chips | full (pill) | Single chip type, always pill |
| Coverage ring | full circle | 80px diameter, central element of recipe card |
| Icon buttons | full (44×44 circle) | Touch target |

### Principle 3: Motion as transparent thinking

Animation shows the user that work is happening *and* what kind of work. Three motion patterns:

| Pattern | What it signals | Spec |
|---|---|---|
| **Radial pulse** | Active inference (e.g., resolving an ingredient, ranking recipes) | `gradient-thinking` radial centered on the active element, scale 1.0 → 1.06 → 1.0, opacity 0.6 → 1.0 → 0.6, 1400ms loop, emphasized easing |
| **Settle** | Result arriving | Coverage ring fills (stroke-dashoffset, 600ms, emphasized) + result card fades in with 8px Y-translate (320ms) |
| **Convergence** | Multiple results lining up | Recipe cards stagger in by score order, 60ms offset per card, max 6 staggered then batch |

No glowing orbs. No purple haze. No "AI is special" sparkle iconography. The motion *is* the AI-state communication. Reduced-motion users get instant settle with a single 200ms opacity fade.

### Principle 4: Softness as antidote to AI-anxiety

> *"When a system is hard to approach, the design must be soft."* — Gemini design library

Surfaces use tonal fills with blurred-edge shadow rather than hard drop shadows. Errors are framed conversationally, not as failure states ("I don't recognize 'wilty kale' — try 'kale'?" rather than "ERROR: ingredient not found"). Empty states are illustrated with circular vessel icons, not bare text.

Shadow tokens:

| Token | Value | Usage |
|---|---|---|
| `shadow-rest` | `0 1px 3px rgba(33,25,22,0.08), 0 4px 12px rgba(33,25,22,0.06)` | Cards at rest |
| `shadow-active` | `0 2px 6px rgba(33,25,22,0.10), 0 12px 32px rgba(33,25,22,0.10)` | Hovered/pressed cards, sheets |
| `shadow-vessel` | `0 0 24px rgba(184,92,56,0.18)` | Active inference glow (paired with radial pulse) |

### Principle 5: Thoughtfully imperfect

Avoid grid-pixel-perfect rigidity. Recipe cards in the list can vary slightly in height (real recipes have different title lengths — don't force-clamp). Coverage rings show fractional fills truthfully (8.3 of 12 ingredients = 69% arc, not rounded to nearest 10%). The "Cooking now" illustration in the empty state is hand-drawn, not iconographic.

## Color palette (unchanged from v1 — Gemini layers on top)

**Seed:** `#B85C38` (terracotta) — Material 3 dynamic palette derives the role tokens below.

### Light scheme
| Role | Hex |
|---|---|
| primary | `#8B3A1F` |
| on-primary | `#FFFFFF` |
| primary-container | `#FFDBCD` |
| on-primary-container | `#360D00` |
| secondary | `#77574C` |
| secondary-container | `#FFDBD1` |
| tertiary | `#695E2F` |
| tertiary-container | `#F2E2A8` |
| error | `#BA1A1A` |
| error-container | `#FFDAD6` |
| surface | `#FFF8F6` |
| surface-container | `#FCE8E4` |
| surface-container-high | `#F6E2DE` |
| on-surface | `#211916` |
| on-surface-variant | `#53433F` |
| outline | `#85736F` |
| outline-variant | `#D8C2BD` |

### Dark scheme
| Role | Hex |
|---|---|
| primary | `#FFB59C` |
| on-primary | `#551F07` |
| primary-container | `#712708` |
| surface | `#19110E` |
| surface-container | `#2D1F1C` |
| on-surface | `#F0DBD7` |

## Typography

**Stack:** `"Google Sans Text", "Inter", system-ui, -apple-system, sans-serif`

Reduced scale (subtracting per "dead simple" — only six type roles, not ten):

| Style | Size | Weight | Line height | Usage |
|---|---|---|---|---|
| display | 48sp | 700 | 56sp | Empty-state hero only |
| headline | 28sp | 600 | 36sp | Screen titles, recipe titles when expanded |
| title | 20sp | 600 | 28sp | Card primary text (recipe name, ingredient name) |
| body | 16sp | 400 | 24sp | Default reading text, instructions |
| label | 13sp | 500 | 18sp | Chip text, button text, metadata |
| caption | 11sp | 400 | 16sp | Attribution, source URLs |

Tracking: −0.01em on display + headline, 0 elsewhere. No all-caps.

## The single screen

There is one screen. It scrolls. Pantry on top, recipes below, both lists. No bottom navigation, no tabs, no separate routes. The PWA is a single page.

```
┌─────────────────────────────────────┐
│  PantryAtlas        🏠 Home Kitchen │ ← Top bar: brand + mode chip
├─────────────────────────────────────┤
│                                     │
│  ╭─────────────────────────────╮    │
│  │ + Add ingredient...         │    │ ← Pill input, full width
│  ╰─────────────────────────────╯    │
│                                     │
│  My Pantry · 7 items                │ ← Section label
│                                     │
│  ╭─────────────────────────╮        │
│  │ 🥕 Butternut squash     │        │ ← Soft cards, 32px radius
│  │    expires in 3 days  🗑│        │
│  ╰─────────────────────────╯        │
│  ╭─────────────────────────╮        │
│  │ 🥬 Kale                 │        │
│  │    expires today      🗑│        │
│  ╰─────────────────────────╯        │
│  …                                  │
│                                     │
│ ─────────────────────────────────── │
│                                     │
│  Recipes you can cook tonight       │ ← Section label
│                                     │
│  ╭─────────────────────────────╮    │
│  │  ⊙ 8/10                     │    │ ← Coverage ring (circle vessel)
│  │     Butternut & Kale Stew   │    │
│  │     2 missing · 30 min      │    │ ← One chip line, not three
│  ╰─────────────────────────────╯    │
│  …                                  │
│                                     │
└─────────────────────────────────────┘
```

### Section A: Top bar

- Fixed top, 64px tall, `surface` fill, no shadow (flat against `gradient-warmth` page bg)
- Leading: "PantryAtlas" wordmark in `title` weight, `primary` color
- Trailing: mode chip — pill shape, `secondary-container` fill, leading icon (🏠 for Home Kitchen, 🍲 for Community Kitchen), label text in `label` style. Tap → mode-switcher sheet (one of two; persists to settings)

That is the entire top bar. No notification bell, no settings gear (settings live in a tap on the mode chip → bottom sheet with mode + about + reset). No menu hamburger.

### Section B: Add-ingredient input (two modalities, one row)

The user adds ingredients two ways: **type** them, or **photograph** the shelf and let the server's Gemma 4 vision pass parse the image. Both feed the same pantry list.

**Layout:** a single pill-shaped input row, 56px tall, full width minus 16px gutters, `surface-container` fill, `outline-variant` 1px border that thickens to `primary` 2px on focus.

- Leading icon (left of text field): `+` in `primary` color, 20px
- Center: text input. Placeholder: "Add ingredient or take a photo..." in `body` size, `on-surface-variant`
- Trailing icon button: `photo_camera` icon, 44×44px circular touch target, `primary-container` fill, `on-primary-container` icon. Always visible. On mobile, tap → opens the device camera (`<input type="file" accept="image/*" capture="environment">`). On desktop, tap → file picker for image upload.

Two flows:

**Flow 1 — Type:** Enter / blur on the text input submits. While the server resolves the typed text to a canonical ingredient, the input's leading edge applies the `gradient-thinking` radial pulse (24px, behind the `+` icon). On success: pulse fades, item slides into the pantry list with `settle` motion. On unrecognized: input shakes 4px (200ms), inline helper text appears below in conversational tone: *"I don't know 'wilty kale' yet — did you mean kale?"*

**Flow 2 — Photograph:** Tap camera icon → device camera UI takes over (native OS layer, not our chrome). User captures a photo. On return, a **photo-review sheet** slides up from the bottom (mobile) or appears as a centered modal (desktop):

- 32px top radius, `surface` fill, `shadow-active`
- Top: drag handle (mobile only), then the captured photo at full width with `gradient-vessel` halo behind it (16px radius, max-height 240px, object-fit: cover)
- Below photo: status region with `gradient-thinking` radial pulse + text "Reading your shelf..." while Gemma 4 vision parses (this is the convergence moment — make it visible; expect 3-8 seconds on a Pi 5)
- After parsing completes: list of detected ingredients with a checkbox per item (all checked by default) + an editable text label per row (user can correct "tomato" → "Roma tomato" inline)
- Header above the list: "Found 6 items — uncheck anything that's not yours" in `body`
- Bottom action row: "Retake photo" (outlined pill, left) + "Add to pantry" (filled `gradient-ember` pill, right). Tap "Add to pantry" → all checked items resolve through the same ingredient-resolution pipeline as typed input, then sheet dismisses, items appear in the pantry list with staggered `settle` motion (60ms offset per item)
- Tap outside / drag handle down (mobile) / close (desktop) → cancels without adding

**Vision dependency note:** This flow assumes the server has Gemma 4's multimodal variant available with a vision-capable endpoint (`POST /navigator/vision/parse-shelf` accepting an image, returning a list of detected ingredient strings). If the server reports vision is unavailable, the camera button shows a tooltip on tap: *"Photo recognition isn't set up on this server — type ingredients for now."* The button stays visible but disabled (50% opacity). This is the only place the UI exposes a backend capability gap.

### Section C: Pantry list

- Section label "My Pantry · N items" in `label`, `on-surface-variant`, 24px above the first card
- Each ingredient is a card:
  - 32px radius, `surface-container` fill, `shadow-rest`, 20px padding, 12px vertical gap between cards
  - Leading: ingredient icon (Material Symbols or hand-drawn SVG) at 24px, `on-surface-variant`
  - Body: canonical name in `title`; if raw text differs from canonical (`"half a squash"` → `"butternut squash"`), show raw text in `caption`, `on-surface-variant` below
  - Trailing: expiration chip + delete icon button
    - Expiration chip: pill, `label` text. ≥3 days → `secondary-container` fill ("3 days"). 1-2 days → `tertiary-container` fill ("2 days"). 0 days → `error-container` fill ("today"). Expired (negative) → struck through, `error` text
    - Delete icon: 44×44px circle target, `delete` icon at 20px, `on-surface-variant`
- Empty state: centered 96px circular vessel illustration (a hand-drawn empty bowl), `display`-size text "Empty pantry", `body` subtext "Type something above — or tap the camera to photograph your shelf"

### Section D: Recipe list

- Section label "Recipes you can cook tonight" in `label` (Home Kitchen mode) or "Recipes you can scale to N meals" (Community Kitchen mode), `on-surface-variant`
- **While the server ranks:** the section label is replaced by a centered radial-pulse vessel (96px, `gradient-thinking`, with `shadow-vessel`) and text "Finding what works..." in `body`. This is the convergence moment — make it visible.
- Each recipe is a card:
  - 32px radius, `surface-container-high` fill, `shadow-rest`, 20px padding, 12px vertical gap
  - **Coverage ring (leading or top):**
    - 80px diameter circle on mobile (top of card, centered); 64px circle on desktop (leading-aligned)
    - SVG: outer ring stroke-width 8px, stroke `tertiary`, track `outline-variant`. Inner fill: `gradient-vessel` radial. Center text: bold fraction "8/10" in `title` size, `on-tertiary-container` color
    - On card enter: stroke-dashoffset animates from full to coverage-percent (`settle` motion)
  - Recipe title in `title` weight, max 2 lines, ellipsis (no force-truncation if it fits naturally)
  - **Single chip line** below title (collapsed from the v1 three-chip row):
    - Format: "N missing · M min" or, for perfect-coverage: "All ingredients · M min"
    - Pill, `label` size, `outline-variant` border, no fill — quiet by default
    - If missing-count ≥ recipe total / 2 → fill `error-container` instead of outline-only
  - Tap card → **expand inline** (NOT a bottom sheet, NOT a side panel):
    - Card height grows with spring motion to show full ingredient list + instructions
    - Ingredient list: each row leading-icon `check_circle` (in pantry, `tertiary` color) or `circle` outline (missing, `outline` color), ingredient text in `body`
    - Instructions: numbered steps in `body` size, each in a soft `surface-container-low` sub-card with 16px radius
    - Source: "From RecipeNLG · CC-BY-NC-4.0" with link icon
    - Bottom of expanded card: two pill buttons — "Add missing to shopping list" (outlined) and "Hide for now" (filled-tonal)
    - Tap collapse icon (chevron-up, top-right of expanded card) or tap card header → collapses with reverse spring
- Empty state: centered 96px circular vessel illustration (empty plate), `display` text "Nothing matches yet", `body` subtext "Add more to your pantry on the shelf above"

### Section E: Mode switcher (one-time sheet)

Triggered on first launch and on mode-chip tap. A bottom sheet on mobile, centered dialog on desktop:

- Sheet has 32px top radius, `surface` fill, drag handle (32×4px pill, `outline-variant`)
- Title: "How are you cooking?" in `headline`
- Two large pill buttons stacked, 80px tall each, with leading 48px circular vessel illustration:
  - "🏠 Home Kitchen — 4 to 10 servings"
  - "🍲 Community Kitchen — 50 to 500 servings"
- Selected button: `gradient-ember` fill, `on-primary` text. Unselected: `surface-container` fill, `on-surface` text. Tap → selects + closes sheet
- Footer text in `caption`: "You can change this anytime from the top bar."

**That is the only mode-related UI.** No inference, no confidence indicator, no override affordance. Ranking adapts under the hood based on the persisted setting.

## Responsive behavior

Single-column on every viewport. On wide screens (>900px), the page centers in a 720px max-width column with `gradient-warmth` extending edge-to-edge behind it. Do **not** introduce a multi-column grid; the dead-simple principle is that there is one stream of content, top to bottom, on every device.

The only desktop-specific change: coverage ring shifts from card-top (centered) to card-leading (left-aligned) so card height is more compact on larger screens.

## Accessibility

- Touch targets ≥ 44×44px (delete icon, mode chip, chip targets all meet)
- Color contrast: all text/background pairs meet WCAG AA. Coverage ring fraction is never the only signal — the chip line repeats the count in words ("2 missing")
- Reduced motion: radial pulse → static gradient halo at the same position; settle → instant fade-in 200ms; convergence stagger → batch
- Screen reader: when results arrive, the section label region is `aria-live="polite"` and updates to "8 recipes found, ranked by ingredient match"

---

## What we subtracted from v1

For Stitch and downstream implementers: this is the deliberate subtraction list. Do **not** add these back even if Stitch suggests them.

- **Bottom navigation bar** → removed. Single screen, no routes.
- **Bento grid for recipes** → removed. Single column always.
- **Bottom sheet RecipeDetail (mobile) and side sheet (desktop)** → removed. Inline expand-in-place instead.
- **Three chip variants per recipe (missing / expiring / substitutions)** → collapsed to one chip line.
- **Extended FAB "Find recipes"** → removed. Results recompute live as pantry changes; no explicit "Find" action.
- **Separate add-ingredient button** → removed. Enter submits.
- **NavigationRail / NavigationDrawer on desktop** → removed.
- **Notification bell, menu hamburger, settings gear in top bar** → removed. Everything lives in the mode chip.
- **Scale-inference UI (confidence indicator, override affordance, inferred-scale badge)** → deferred to v0.3. v0.2 is a one-time settings choice.
- **Filter sidebar on desktop (cuisine / time / dietary)** → deferred to v0.3.

The Gemini gradients and circles add visual *richness*, not structural complexity. The screen got simpler, not busier.

---

## Stitch handoff notes

When regenerating mockups via Stitch against project `12279110322585036502`:

1. The design system already uploaded to that project is v1 (M3 Expressive baseline). Use `edit_screens` and `generate_variants` to evolve rather than `create_project`.
2. Submit this DESIGN.md via `upload_design_md` (replaces the prior brief).
3. Regenerate the three screens: PantryEditor → RecipeResults → RecipeDetail collapse into **one** screen (the merged single-screen spec above). Generate **only** mobile + desktop variants of that one screen (4 PNGs total, down from 6).
4. Then generate three sheet variants (mobile only — desktop just centers them):
   - Mode-switcher sheet
   - Photo-review sheet (parsed ingredients with checkboxes)
   - Expanded recipe card state (inline expansion within the recipe list)
5. Reference the Gemini principles section explicitly in any text prompts to Stitch — call out "radial pulse during inference", "gradient as energy not decoration", "circles as vessels."

---

*Design system version: PantryAtlas Navigator v0.2.0 · Gemini-influenced · Material 3 base · Seed #B85C38 · 2026-05-27*
