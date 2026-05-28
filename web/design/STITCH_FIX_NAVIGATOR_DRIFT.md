# Stitch fix — navigator-mobile bottom-nav drift

> **What:** One targeted `edit_screens` call against the existing Stitch project. No new screens, no design-system change.
>
> **Why:** Stitch's v2 rendering of `navigator-mobile` added a 3-tab bottom navigation bar ("Pantry / Recipes / List"), but DESIGN.md "What we subtracted from v1" explicitly removes it — the PWA is a single scrolling screen with no routes.
>
> **What we're NOT fixing in Stitch:** `navigator-desktop` has a "© 2024 PantryAtlas. Thoughtfully Imperfect AI. Privacy · Terms · Support" footer. The operator confirmed (2026-05-27) that the footer concept is fine but belongs on the marketing page only, not the navigator. The navigator-desktop.png is left with this stale footer; implementers follow DESIGN.md (which says no footer on the navigator screen) rather than the mockup. The correct footer copy lives in `web/marketing/DESIGN.md` Section "Footer" with the right year (© 2026) and the right link grid.
>
> **How to use:** Open a terminal on the Pi, run `agy -i`, paste everything between the BEGIN/END markers below as a single message. Expect ~3–5 minutes (single edit + single refetch). When agy reports done, reply here with `"agy done"` (or paste the refreshed PNG URL) and I'll fetch + commit.

--- BEGIN PROMPT ---

You're fixing one drift issue in an existing Stitch project. One edit, one refetch. Use only `edit_screens` and `get_screen`.

## Project

ID: `12279110322585036502`

## Edit

### navigator-mobile (screen ID `2aaab8b6eb994c1ca91d810c5da2f568`)

Call `edit_screens` with this instruction (verbatim):

> Remove the 3-tab bottom navigation bar at the bottom of this screen ("Pantry / Recipes / List" icons). The PantryAtlas PWA is a single scrolling screen with no routes — the pantry list and the recipe list are both on this same screen, stacked vertically. After removal, the screen should simply end after the last recipe card (or have generous bottom padding for safe-area). Do not replace the bottom nav with anything. Do not add a FAB. The top bar (PantryAtlas wordmark + Home Kitchen mode chip) stays exactly as is.

### After the edit lands

Call `get_screen` for `2aaab8b6eb994c1ca91d810c5da2f568` and save the refreshed PNG to disk at this exact path (overwrite the existing file):

```
/home/craigm26/pantryatlas/web/design/screens/navigator-mobile.png
```

The JSON sidecar at `web/design/screens/navigator-mobile.json` should be left as-is (screen ID and dimensions haven't changed).

### Constraints

- Use only `edit_screens` and `get_screen`. Do not call `generate_screen_from_text`, `generate_variants`, `create_design_system`, `upload_design_md`, or `edit_screens` on any other screen.
- Do not touch any other screens: `navigator-desktop`, `mode-switcher-sheet`, `photo-review-sheet`, `marketing-hero-*`, `marketing-setup-*`. Leave them exactly as they are.
- Do not ask for clarification. If a tool call returns an error, retry once with the same parameters; if it still fails, report the error and stop.

When the PNG has been refetched and saved, report briefly: "Done. navigator-mobile refreshed."

--- END PROMPT ---
