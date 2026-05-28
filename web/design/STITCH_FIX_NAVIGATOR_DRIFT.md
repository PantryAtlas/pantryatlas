# Stitch fix — navigator-mobile bottom-nav drift (round 2: variants approach)

> **What:** Use `generate_variants` to produce 3 new screen variants of navigator-mobile WITHOUT a bottom navigation bar. We pick the best one, overwrite navigator-mobile.png with it, and update the JSON sidecar.
>
> **Why round 2:** The earlier `edit_screens` call (round 1) reported success but produced a bit-identical PNG — Stitch's model rejected the edit silently, probably defaulting to "mobile app must have bottom nav." `generate_variants` produces new screens from scratch off a base, so the model has more latitude to actually drop the element. We also frame the intent positively ("single-page app, no routes") with reinforced negative constraints.
>
> **What we're NOT fixing in Stitch:** `navigator-desktop` has a "© 2024 PantryAtlas... Privacy · Terms · Support" footer. The operator confirmed (2026-05-27) the footer concept belongs on the marketing page only, not the navigator. Implementers follow DESIGN.md (no footer on navigator) over the mockup. MARKETING.md footer has correct © 2026 + link grid.
>
> **How to use:** Open a terminal on the Pi, run `agy -i`, paste everything between the BEGIN/END markers below as a single message. Expect ~5–8 minutes (one generate_variants call producing 3 variants + three get_screen refetches). When agy reports done, paste back the three variant URLs (or screen IDs) and I'll fetch all three, show them to you, and you pick which one becomes the canonical navigator-mobile.

--- BEGIN PROMPT ---

You're producing 3 variants of an existing Stitch screen with one specific structural change — removing the bottom navigation bar. The PantryAtlas PWA has no routes; the screen is a single scroll.

## Project

ID: `12279110322585036502`

## Step 1 — Call `generate_variants`

Base screen ID: `2aaab8b6eb994c1ca91d810c5da2f568` (current navigator-mobile)
Number of variants: 3

Use this instruction verbatim:

> Produce 3 design variants of this screen with this single structural change: REMOVE the bottom navigation bar entirely.
>
> Design intent (positive framing): This is a single-page Progressive Web App. There are no routes, no sub-screens, no tabs. The entire user experience fits on this one vertically scrolling screen. The pantry list and the recipe list are both on this same screen, stacked vertically. There is no other screen for the user to navigate to.
>
> Hard constraints (do not violate):
> - NO bottom navigation bar of any kind
> - NO tabs at the bottom of the screen
> - NO floating action button (FAB)
> - NO icons positioned along the bottom edge of the screen
> - NO "Pantry / Recipes / List" or any similar text labels at the bottom
> - The bottom of the screen ends with 32px of empty padding below the last recipe card. Nothing else.
>
> Keep everything else exactly as it is:
> - Top bar: PantryAtlas wordmark + "🏠 Home Kitchen" mode chip
> - Pill-shaped "Add ingredient or take a photo..." input with leading + icon and trailing camera icon button
> - "MY PANTRY · 7 ITEMS" section header
> - 3 ingredient cards (Butternut Squash 3 days, Kale today, Onion 5 days), each with a circular ingredient avatar, an expiration chip, and a delete X
> - "RECIPES YOU CAN COOK TONIGHT" section header
> - Recipe cards with circular coverage rings (8/10 and 6/10) and single chip lines ("2 missing · 30 min", "4 missing · 20 min")
>
> Vary across the 3 variants only in how the bottom of the screen is treated:
> - Variant A: simple bottom padding, screen just ends
> - Variant B: a subtle bottom safe-area spacer with a faint horizontal divider line at the very bottom
> - Variant C: a sentence of attribution text at the bottom in caption size — "Recipe data: RecipeNLG (CC-BY-NC-4.0)"

## Step 2 — Save all 3 variants to disk

For each of the 3 returned variant screen IDs, call `get_screen` and save the PNG with these exact paths:

```
/home/craigm26/pantryatlas/web/design/screens/navigator-mobile-variant-a.png
/home/craigm26/pantryatlas/web/design/screens/navigator-mobile-variant-b.png
/home/craigm26/pantryatlas/web/design/screens/navigator-mobile-variant-c.png
```

Also save the JSON metadata sidecar for each:

```
/home/craigm26/pantryatlas/web/design/screens/navigator-mobile-variant-a.json
/home/craigm26/pantryatlas/web/design/screens/navigator-mobile-variant-b.json
/home/craigm26/pantryatlas/web/design/screens/navigator-mobile-variant-c.json
```

Each JSON should contain at minimum: `{name, title, width, height, deviceType}`.

## Step 3 — Report back

Report the three screen IDs and three CDN URLs back to the operator so they can hand them to Claude for review.

Format:

```
Variant A: screen_id=<id> url=<https://lh3.googleusercontent.com/aida/...>
Variant B: screen_id=<id> url=<https://lh3.googleusercontent.com/aida/...>
Variant C: screen_id=<id> url=<https://lh3.googleusercontent.com/aida/...>
```

## Constraints

- Use only `generate_variants` and `get_screen`. Do NOT call `edit_screens` (we tried it; it no-op'd silently). Do NOT call `generate_screen_from_text`, `create_design_system`, or `upload_design_md`.
- Do not touch any other screens: `navigator-desktop`, `mode-switcher-sheet`, `photo-review-sheet`, `marketing-hero-*`, `marketing-setup-*`. Leave them exactly as they are.
- Do not overwrite the existing `navigator-mobile.png` or `navigator-mobile.json` yet — we keep them as the "before" reference until the operator picks a winner.
- Do not ask for clarification. If a tool call returns an error, retry once with the same parameters; if it still fails, report the error and stop.

When all 3 variants are saved and the report block is printed, you're done.

--- END PROMPT ---
