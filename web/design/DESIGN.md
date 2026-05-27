# PantryAtlas Navigator v0.2.0 — Design Brief

## Brand

**PantryAtlas** is a local-first culinary AI running on a Raspberry Pi 5. Open source under Apache 2.0, published at pantryatlas.org. Its mission is a single clear idea: *"use what you have, not what a recipe demands."* The product is for people who open their fridge, see a half-used butternut squash and some wilting kale, and want real recipes — not a shopping list.

The brand voice is warm, practical, and low-friction. No subscription gates, no cloud dependency, no surveillance of your eating habits. The UI should feel like a well-designed kitchen notebook: organized, tactile, and quietly intelligent. Trust is earned through clarity and speed, not through animated sparkles.

PantryAtlas connects pantry state (what you have, when it expires) to a RecipeNLG corpus (hundreds of thousands of real recipes) through a coverage scoring engine running entirely on-device. The navigator interface is the primary touchpoint for this connection.

## Aesthetic

Material 3 Expressive, inspired by the Google Spark design language. The UI should feel generous and modern: soft tonal surfaces, ample whitespace between elements, bento-style card grids on wider viewports, and smooth spring-physics motion. Typography is expressive and varied in scale — headline text carries personality while body text stays readable at small sizes.

This is explicitly **not** the generic AI-app aesthetic (dark backgrounds, purple gradients, glowing orbs). PantryAtlas deals in food, warmth, and daily life. The visual language should feel like a farmers' market app built by a design team that actually cooks.

Surfaces use tonal fill (Material 3 surface container tiers) rather than white-on-white. Cards have generous corner radii. Elevation is subtle: soft shadow on interacted elements, flat on resting cards. The color palette is grounded in terracotta — a warm, food-associated hue that reads as intentional without being aggressive.

## Color Palette

**Seed color:** `#B85C38` (terracotta)

Material 3 dynamic palette derived from seed:

### Light Scheme
| Role | Hex | Usage |
|---|---|---|
| primary | `#8B3A1F` | Filled buttons, active states, FAB |
| on-primary | `#FFFFFF` | Text/icons on primary |
| primary-container | `#FFDBCD` | Tonal buttons, selected chips |
| on-primary-container | `#360D00` | Text on primary-container |
| secondary | `#77574C` | Secondary actions, supporting UI |
| on-secondary | `#FFFFFF` | Text on secondary |
| secondary-container | `#FFDBD1` | Expiration warning chips (mild) |
| on-secondary-container | `#2C150D` | Text on secondary-container |
| tertiary | `#695E2F` | Accent elements, coverage rings |
| on-tertiary | `#FFFFFF` | Text on tertiary |
| tertiary-container | `#F2E2A8` | Coverage progress arc fill |
| on-tertiary-container | `#221B00` | Text on tertiary-container |
| error | `#BA1A1A` | Missing ingredients, expiry danger |
| on-error | `#FFFFFF` | Text on error |
| error-container | `#FFDAD6` | Expiration warning (urgent) |
| on-error-container | `#410002` | Text on error-container |
| surface | `#FFF8F6` | Page backgrounds |
| surface-container-lowest | `#FFFFFF` | Elevated card backgrounds |
| surface-container-low | `#FFF1EE` | Subtle section tints |
| surface-container | `#FCE8E4` | Default card fill |
| surface-container-high | `#F6E2DE` | Raised card fill (recipe cards) |
| surface-container-highest | `#F0DBD7` | Highest elevation surfaces |
| on-surface | `#211916` | Primary text |
| on-surface-variant | `#53433F` | Secondary text, metadata |
| outline | `#85736F` | Borders, dividers |
| outline-variant | `#D8C2BD` | Subtle dividers |

### Dark Scheme
| Role | Hex |
|---|---|
| primary | `#FFB59C` |
| on-primary | `#551F07` |
| primary-container | `#712708` |
| on-primary-container | `#FFDBCD` |
| surface | `#19110E` |
| surface-container | `#2D1F1C` |
| surface-container-high | `#382B27` |
| on-surface | `#F0DBD7` |

## Typography

**Type scale:** Material 3 Expressive ramp.

**Font stack:** `"Google Sans Text", "Inter", system-ui, -apple-system, sans-serif`

| Style | Size | Weight | Line height | Usage |
|---|---|---|---|---|
| display-large | 57sp | 700 | 64sp | Splash / hero only |
| headline-large | 32sp | 700 | 40sp | Section titles |
| headline-medium | 28sp | 700 | 36sp | Screen titles, sheet headers |
| title-large | 22sp | 500 | 28sp | Card primary label |
| title-medium | 16sp | 500 | 24sp | Sub-section labels |
| body-large | 16sp | 400 | 24sp | Instructions, long-form text |
| body-medium | 14sp | 400 | 20sp | Secondary card text |
| label-large | 14sp | 500 | 20sp | Button labels, chip labels |
| label-medium | 12sp | 500 | 16sp | Supporting metadata |
| label-small | 11sp | 500 | 16sp | Attribution, legal |

Headings are set in weight 700 with tight tracking (−0.02em). Body text is weight 400, tracking 0. Chip labels are weight 500, all-caps off.

## Shape

Corner radii follow the Material 3 shape scale:

| Level | Radius | Usage |
|---|---|---|
| none | 0px | Dividers only |
| extra-small | 4px | Tooltip bubbles |
| small | 8px | Input field corners |
| medium | 12px | Navigation bar |
| large | 20px | Filled/tonal buttons, large chips |
| extra-large | 28px | Cards, bottom sheets (top corners), dialogs |
| full | 50% / pill | FAB, avatar chips, circular icon buttons |

Cards use `extra-large` (28px) radius. FAB uses full pill. Bottom sheet on mobile clips to `extra-large` on the top-left and top-right corners only; drag handle is centered above content at 32px wide × 4px tall.

Elevation: shadow offset `0 2px 6px rgba(33, 25, 22, 0.12)` at rest; `0 6px 16px rgba(33, 25, 22, 0.20)` on hover/press. No harsh drop shadows. Tonal surface differentiation is preferred over deep shadows.

## Motion

**Easing:** `cubic-bezier(0.2, 0.0, 0, 1.0)` — M3 emphasized easing (spring-like, overshoots slightly then settles).

**Durations:**
- Instant state changes (ripple start): 100ms
- Micro-interactions (chip color shift): 200ms
- Card entry (fade + translate-Y 12px): 280ms
- Bottom sheet slide-up: 350ms
- Screen transitions: 400ms

**Stagger:** List items and grid cards enter with a 50ms stagger offset per item (first = 0ms, second = 50ms, third = 100ms, etc.). Maximum 6 items staggered; beyond that, all enter together.

**Card hover/press:** `transform: scale(1.02)` + elevation bump to hover shadow on hover. Press: `scale(0.98)` + fast 100ms duration. Return to rest: 280ms emphasized easing.

**Coverage ring animation:** SVG stroke-dashoffset animation from 0 to the coverage percentage value, duration 600ms, easing emphasized, triggered on card enter (after stagger delay).

## Layout

**Mobile-first.** Single column on viewports ≤600px. Navigation via persistent bottom bar (Material 3 NavigationBar) on mobile.

**Tablet / Desktop (>600px):** Bento grid using `display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px;` for recipe cards. Navigation moves to a NavigationDrawer or NavigationRail on the left.

**Spacing system:** 4px base unit. Component padding: 16px standard, 24px for cards, 32px for page gutters on desktop.

**App bar:** Sticky top. Small variant (56px tall) on scroll; expanded (152px) at top of scroll for primary screens. Material 3 `TopAppBar` with centered or leading title.

---

## Screen Specifications

### Screen 1: PantryEditor

The primary data-entry screen. Users add pantry items, see resolution status (did the AI understand the ingredient?), and manage expiration dates.

**Layout:**
- Sticky `SmallTopAppBar` with "PantryAtlas" title (title-large, primary color), leading `menu` icon button, trailing `notifications` icon button
- Below bar: padded page title "My Pantry" in headline-medium
- Outlined `TextField` (full width, 16px horizontal margin) with a leading `add_shopping_cart` Material Symbol icon and placeholder text "Add ingredient (e.g. half a butternut squash)"
- `Add` filled-tonal button to the right of the field (or pressing Enter submits)
- Resolution status chip directly below the text field: terracotta-tonal (`primary-container` fill, `on-primary-container` text) when the ingredient resolved to a canonical pantry item; `error-container` fill with `on-error-container` text when unresolved with "Unrecognized — try a different name" label; hidden when field is empty
- Pantry item list below (vertical, no separator lines):
  - Each item is a filled card (`surface-container-high` fill, `extra-large` radius, 24px padding)
  - Leading: `restaurant_menu` icon in `on-surface-variant` color
  - Body: `canonical_name` in title-large; if `raw_text` differs from `canonical_name`, show `raw_text` in body-medium `on-surface-variant` below
  - Trailing: expiration chip (`label-large`, `secondary-container` fill normally; shifts to `error-container` fill when ≤1 day remaining) + `delete` icon button (`on-surface-variant` color, 44×44px touch target)
  - Empty state: centered `kitchen` icon at 80px, "Your pantry is empty" in headline-medium, "Add ingredients above to get started" in body-large, and a filled "Add your first ingredient" CTA button

**Mobile vs Desktop differences:**
- Mobile: single-column list, bottom navigation bar with Pantry / Recipes / Settings tabs
- Desktop: left navigation rail with icon+label for same tabs; pantry list displayed in a 2-column bento grid (2 cards per row on wider viewports); FAB replaced by inline "Add" button attached to the text field

### Screen 2: RecipeResults

The discovery screen. Ranked recipe cards in a bento grid, scored by how many pantry items each recipe can use (coverage score).

**Layout:**
- Sticky `SmallTopAppBar` with "Find Recipes" title and back arrow
- Subtitle line below bar: "X recipes found · Y ingredients in pantry" in label-large, `on-surface-variant`
- Bento grid of recipe cards (auto-fit, minmax 280px):
  - Card fill: `surface-container-high`, `extra-large` radius, 24px padding
  - Top of card: large animated SVG coverage ring (64px diameter). Stroke color = `tertiary`, track color = `outline-variant`. Center text: bold fraction ("8/10") in title-large + "in pantry" in label-medium below
  - Recipe title in title-large (2 lines max, ellipsis on overflow), `on-surface` color
  - Chip row (horizontal scroll if overflow):
    - If missing-count > 0: `error-container` chip "Missing N" with `highlight_off` icon
    - If expiring-used > 0: `secondary-container` chip "Uses N expiring" with `schedule` icon
    - If substitution-count > 0: `tertiary-container` chip "N substitutions" with `swap_horiz` icon
  - Full-width `FilledTonalButton` "View recipe" at card bottom
  - Below button: `label-small` attribution "RecipeNLG · CC-BY-NC-4.0" in `on-surface-variant`
- Extended FAB (mobile: fixed bottom-right, 16px margin; desktop: inline above grid):
  - `search` icon + "Find recipes" label
  - Fill: `primary-container`, label color: `on-primary-container`
- Empty state: centered `restaurant_menu` icon at 96px, "Add ingredients to start" in headline-medium, "Your pantry is empty — add some ingredients on the Pantry tab" in body-large, filled "Go to Pantry" CTA

**Mobile vs Desktop differences:**
- Mobile: 1-column stack of recipe cards; Extended FAB pinned to bottom-right
- Desktop: 3-column bento grid; Extended FAB replaced by filled-tonal button in the top bar area; filter sidebar on the left (filter by cuisine, time, dietary restriction) — initially collapsed

### Screen 3: RecipeDetail

Full recipe display with pantry-match annotation. Opens as a bottom sheet on mobile (slides up, partially obscuring the recipe list below), side sheet on desktop (right panel).

**Layout:**
- **Mobile — Bottom Sheet:**
  - Drag handle (32×4px, `outline-variant`, pill shape) at top center
  - Top corners: `extra-large` radius (28px)
  - Header: recipe title in headline-medium, `on-surface` color; score chip ("8/10 pantry match") in `tertiary-container`
  - Section: "Ingredients" in title-medium; vertical list of ingredient rows:
    - Each row: leading `check_circle` icon (`tertiary` color, 20px) when ingredient is in pantry; `radio_button_unchecked` icon (`outline` color) when missing; ingredient text in body-large; quantity in label-medium `on-surface-variant` trailing
    - Missing items rendered with `on-surface-variant` text and a "missing" micro-badge
    - Expiring items: `schedule` icon + "expires soon" label-small in `secondary` color
  - Section: "Instructions" in title-medium; numbered steps in body-large; each step is a card (`surface-container-low`, `medium` radius, 12px padding) with step number in a filled circle (`primary`, white text)
  - Section: "Source" in title-medium; source name in body-medium; tappable URL link ("View original recipe") in `primary` color with `open_in_new` trailing icon
  - Attribution footer: "Recipe data from RecipeNLG · CC-BY-NC-4.0" in label-small, `on-surface-variant`
  - Fixed bottom bar: "Add missing to list" outlined button + "Save recipe" filled button, both 50% width

- **Desktop — Side Sheet:**
  - Right panel, 400px wide, full viewport height, `surface-container-lowest` background
  - Top bar inside panel: "Recipe Detail" title + `close` icon button
  - Same content sections as mobile but in a single scrollable column
  - No drag handle; no fixed bottom bar — buttons appear inline below source section

---

*Design system version: PantryAtlas Navigator v0.2.0 · Material 3 Expressive · Seed #B85C38*
