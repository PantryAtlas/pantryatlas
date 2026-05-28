# Stitch re-orchestration prompt — PantryAtlas v0.2.0 (Gemini-influenced rewrite)

> **Operator instructions:** Open a terminal on the Pi and run `agy -i` (or just `agy` interactive). Paste **everything below the `--- BEGIN PROMPT ---` line** as a single message. Don't add anything before or after. agy will execute Stitch MCP calls and write artifacts to disk via its Bash access. Expect the run to take 15–30 minutes.
>
> When agy reports done, return here and reply with `"agy done"` (or paste the last 30 lines of its output). I'll verify the on-disk artifacts and commit them.
>
> **What this run produces:**
> - 4 navigator PNG mockups (1 merged single-screen × mobile + desktop, plus 2 mode-switcher + photo-review sheet mockups)
> - 4 marketing PNG mockups (hero + setup-walkthrough × mobile + desktop)
> - Updated `web/design/design-system.json` with Gemini-language additions (gradient tokens, expanded shape scale)
> - Both DESIGN.md files re-uploaded to the existing Stitch project so the project state matches the brief

--- BEGIN PROMPT ---

You are orchestrating a Stitch design regeneration for the PantryAtlas v0.2.0 navigator and a sibling marketing page for pantryatlas.org. Both design briefs have been rewritten by your collaborator (Claude in Claude Code). Read them, then use the Stitch MCP tools to evolve an existing Stitch project to match.

## Project

Stitch project ID: `12279110322585036502`
Project URL: https://stitch.google.com/projects/12279110322585036502

This project already exists from a v1 generation run. Do NOT create a new project. Use `edit_screens`, `generate_variants`, and `upload_design_md` to evolve it.

## Two design briefs

Read both files in full before calling any Stitch tools:

1. `/home/craigm26/pantryatlas/web/design/DESIGN.md` — the navigator app brief (one scrolling screen with pantry + recipes, two sheets, Gemini-influenced visual language)
2. `/home/craigm26/pantryatlas/web/marketing/DESIGN.md` — the pantryatlas.org landing page brief (hero, what-it-is, two-kitchens, 4-step setup, features, open-source, two-CTA cards)

Both briefs share a visual system: terracotta seed `#B85C38`, Gemini gradients (`gradient-thinking`, `gradient-warmth`, `gradient-vessel`, `gradient-ember`), circles as foundational vessels, soft blurred shadows, pill-shaped buttons/chips, 32px card radii, `"Google Sans Text"` type stack.

## Tasks (execute in order)

### Task A — Re-upload both design briefs

1. Call `upload_design_md` with the navigator brief content (read `/home/craigm26/pantryatlas/web/design/DESIGN.md`). This replaces the v1 brief in the project.
2. Call `upload_design_md` again with the marketing brief content (read `/home/craigm26/pantryatlas/web/marketing/DESIGN.md`). If the tool requires a unique name per upload, name the second one `MARKETING.md`.
3. Call `create_design_system_from_design_md` to regenerate the design system from the navigator brief (it's the primary source — marketing inherits). Save the returned design-system JSON to `/home/craigm26/pantryatlas/web/design/design-system.json` (overwrite the existing file).

### Task B — Generate the navigator screen (one merged scrolling screen)

The v1 project has three separate screens (PantryEditor, RecipeResults, RecipeDetail). v2 collapses them into ONE scrolling screen. Use `edit_screens` or `generate_screen_from_text` to produce:

1. **navigator-mobile** — single scrolling screen at 390×844 (iPhone 15 portrait). Top bar with PantryAtlas wordmark + mode chip ("🏠 Home Kitchen"), pill add-ingredient input with `+` leading icon + `photo_camera` trailing icon button, "My Pantry · 7 items" section header, 3 ingredient cards (butternut squash 3d, kale today, onion 5d), section divider, "Recipes you can cook tonight" section header, 2 recipe cards with 80px coverage rings (8/10 and 6/10) and single chip lines.
2. **navigator-desktop** — same content at 1440×900, single centered 720px column with `gradient-warmth` extending edge-to-edge behind. Coverage rings shift to card-leading position.
3. **mode-switcher-sheet** — bottom sheet at 390×600, drag handle, "How are you cooking?" headline, two large 80px pill buttons stacked (🏠 Home Kitchen / 🍲 Community Kitchen), `gradient-ember` fill on selected. Caption footer.
4. **photo-review-sheet** — bottom sheet at 390×844, drag handle, captured photo at top with `gradient-vessel` halo, "Reading your shelf..." radial-pulse state on top, then "Found 6 items — uncheck anything that's not yours" with 6 checkbox rows (each editable), bottom action row "Retake photo" outlined + "Add to pantry" filled `gradient-ember`.

Use Gemini principles explicitly in your prompts to Stitch: *"radial pulse using gradient-thinking during inference moments"*, *"circles as foundational vessels — coverage rings, input pills, buttons all pill-shaped"*, *"soft blurred shadows, not hard drop shadows"*, *"thoughtfully imperfect — slight asymmetry, hand-drawn vessel illustrations"*. Do NOT generate Google's four-color dots — terracotta only.

### Task C — Generate the marketing page (hero + setup walkthrough)

Stitch can extrapolate the rest of the page from the brief; we only need the two highest-stakes sections rendered.

5. **marketing-hero-mobile** — viewport 390×844, hero section per `web/marketing/DESIGN.md` Section 1: fixed top-left wordmark "PantryAtlas · Free · Open source · Runs on a small computer in your kitchen", full-bleed `gradient-warmth` bg with top-right `gradient-thinking` blob (60vw, blur 80px, opacity 0.4), centered 240px circular vessel illustration (Pi + cutting board + vegetables), display headline *"Your kitchen's smart pantry. Lives in your kitchen."*, body subhead *"A small computer you set up once. It helps you cook delicious food from what's already on your shelf — whether you're feeding four people or four hundred. Free, open source, and nothing leaves your kitchen."*, two CTA pills ("How to set it up" filled gradient-ember + "See it on GitHub →" outlined), scroll-cue chevron.
6. **marketing-hero-desktop** — same content at 1440×900, hero illustration shifts to left of headline (two-column flex), CTAs in a row.
7. **marketing-setup-mobile** — viewport 390×1800 (long scroll), Section 4 setup walkthrough only: heading "Set it up in four steps", sub-line "About 30 minutes the first time. Then it just sits there working.", 4 numbered step cards stacked. Step 1 contains TWO sub-option cards (Pi 5 default / Coral Dev Board alternative). Steps 2-4 each with their illustrations.
8. **marketing-setup-desktop** — same content at 1440×1400, step cards full-width with illustrations on the right side of each card body.

### Task D — Save all artifacts

For each generated screen, use `get_screen` to fetch the rendered PNG and save with these exact paths:

```
/home/craigm26/pantryatlas/web/design/screens/navigator-mobile.png
/home/craigm26/pantryatlas/web/design/screens/navigator-desktop.png
/home/craigm26/pantryatlas/web/design/screens/mode-switcher-sheet.png
/home/craigm26/pantryatlas/web/design/screens/photo-review-sheet.png
/home/craigm26/pantryatlas/web/design/screens/marketing-hero-mobile.png
/home/craigm26/pantryatlas/web/design/screens/marketing-hero-desktop.png
/home/craigm26/pantryatlas/web/design/screens/marketing-setup-mobile.png
/home/craigm26/pantryatlas/web/design/screens/marketing-setup-desktop.png
```

Also save each screen's JSON metadata sidecar:

```
/home/craigm26/pantryatlas/web/design/screens/<screen-name>.json
```

If the v1 PNGs (`pantry-editor-mobile.png`, etc.) still exist in that directory, leave them — your collaborator will reconcile.

### Task E — Update orchestration log

Append a final summary line to `/home/craigm26/pantryatlas/web/design/stitch-orchestration-v2.log` listing every file you wrote with its size, like:

```
WROTE web/design/screens/navigator-mobile.png 47823 bytes
WROTE web/design/screens/navigator-desktop.png 58102 bytes
...
DONE 8 screens + 1 design system + 2 briefs uploaded to project 12279110322585036502
```

## Constraints

- Use Stitch MCP tools only. Do not call any other tools unless necessary for file I/O.
- Do not ask for clarifications. Everything you need is in the two DESIGN.md files. If a tool call returns an error, retry with a different parameter or move on — do not pause for confirmation.
- Do not regenerate the v1 screens (PantryEditor / RecipeResults / RecipeDetail) — they're being replaced, not edited.
- The marketing brief is a *sibling* artifact. Do not merge its visual decisions into the navigator screens.
- Honor the explicit subtraction list in each DESIGN.md "What we subtracted" / "What's NOT on the marketing page" sections. Do not re-add subtracted elements even if Stitch suggests them.

When all 8 PNGs and 8 JSON sidecars exist on disk and the log line is appended, you are done. Report briefly: "Done. 8 screens generated. Log at web/design/stitch-orchestration-v2.log."

--- END PROMPT ---
