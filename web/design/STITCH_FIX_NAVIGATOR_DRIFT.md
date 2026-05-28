# Stitch fix — navigator mockup drift

> **What:** Two targeted edits via `edit_screens` against the existing Stitch project. No new screens, no design-system change.
>
> **Why:** Stitch's v2 generation introduced two spec violations:
> 1. `navigator-mobile` has a 3-tab bottom navigation bar ("Pantry / Recipes / List") — but DESIGN.md "What we subtracted from v1" explicitly removes it. The PWA is a single scrolling screen with no routes.
> 2. `navigator-desktop` has a footer with "© 2024 PantryAtlas. Thoughtfully Imperfect AI. Privacy · Terms · Support" — wrong year (today is 2026-05-27), and the spec doesn't call for a footer on the navigator screen.
>
> **How to use:** Open a terminal on the Pi, run `agy -i`, paste everything between the BEGIN/END markers below as a single message. Expect ~5–10 minutes (single tool call per screen, no PNG generation overhead since `get_screen` only refetches). When agy reports done, reply here with `"agy done"` and I'll fetch the updated PNGs and commit.

--- BEGIN PROMPT ---

You're fixing two drift issues in an existing Stitch project. No new screens, no design system changes. Use only `edit_screens` and `get_screen`.

## Project

ID: `12279110322585036502`

## Edits

### Edit 1 — navigator-mobile (screen ID `2aaab8b6eb994c1ca91d810c5da2f568`)

Call `edit_screens` with this instruction (verbatim):

> Remove the 3-tab bottom navigation bar at the bottom of this screen ("Pantry / Recipes / List" icons). The PantryAtlas PWA is a single scrolling screen with no routes — the pantry list and the recipe list are both on this same screen, stacked vertically. After removal, the screen should simply end after the last recipe card (or have generous bottom padding for safe-area). Do not replace the bottom nav with anything. Do not add a FAB. The top bar (PantryAtlas wordmark + Home Kitchen mode chip) stays exactly as is.

### Edit 2 — navigator-desktop (screen ID `70d4b139d95d44cca88441c88ec0bbc4`)

Call `edit_screens` with this instruction (verbatim):

> Remove the bottom footer that says "© 2024 PantryAtlas. Thoughtfully Imperfect AI. Privacy · Terms · Support". The navigator screen is the in-app surface, not a marketing page, and the design brief does not call for a footer on it. After removal, the screen should end after the last recipe card with generous bottom padding. Do not replace it with anything. The top bar (PantryAtlas wordmark + Home Kitchen mode chip) stays exactly as is.

### After both edits land

Call `get_screen` for each screen ID and save the refreshed PNG to disk at these exact paths (overwrite the existing files):

```
/home/craigm26/pantryatlas/web/design/screens/navigator-mobile.png
/home/craigm26/pantryatlas/web/design/screens/navigator-desktop.png
```

The JSON sidecars at `web/design/screens/navigator-mobile.json` and `web/design/screens/navigator-desktop.json` should be left as-is (the screen IDs and dimensions haven't changed).

### Constraints

- Use only `edit_screens` and `get_screen`. Do not call `generate_screen_from_text`, `generate_variants`, `create_design_system`, or `upload_design_md`.
- Do not regenerate, edit, or touch any other screens: `mode-switcher-sheet`, `photo-review-sheet`, or any of the 4 marketing screens (`marketing-hero-*`, `marketing-setup-*`).
- Do not ask for clarification. If a tool call returns an error, retry once with the same parameters; if it still fails, report the error and stop.
- Do not edit the design system.

When both PNGs have been refetched and saved, report briefly: "Done. navigator-mobile and navigator-desktop refreshed."

--- END PROMPT ---
