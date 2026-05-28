# PantryAtlas Session Handoff (2026-05-27, late session → next)

> Written before context compaction. Post-compaction self: read this + the memory anchor `project_pantryatlas_v0_2_0_in_progress_2026_05_27.md` first.

## TL;DR — where we are

- **v0.1.0 SHIPPED**, public at https://github.com/PantryAtlas/pantryatlas.
- **Marketing site LIVE** at https://pantryatlas.pages.dev (CF Pages project `pantryatlas`, account Civqo). Custom domain `pantryatlas.org` + www→apex redirect are operator dashboard steps (wrangler can't attach Pages custom domains). Source: `web/marketing/site/` (static, cool-Gemini, self-hosted DM Sans, strict CSP, no tracking). Re-deploy after edits: `npx wrangler@latest pages deploy web/marketing/site --project-name pantryatlas --branch main`.
- **v0.2.0 navigator: 11 of 15 tasks DONE** on `feat/navigator-v0.2.0` @ `a13d7d7`, all pushed. 146 Python tests green. Working tree clean as of this write.

## Design pivot (load-bearing)

The whole project pivoted **from terracotta to the cool Gemini gradient** (blue `#4285F4` → indigo → purple `#9B72CB` → magenta `#D96570`) over Material-3 neutral surfaces, self-hosted **DM Sans**, Material line-icons, a "Built with Gemma · on-device" badge. `web/design/DESIGN.md` (navigator brief) + `web/marketing/DESIGN.md` + `web/design/design-system.json` are all cool-Gemini now and are the SOURCE OF TRUTH. The 8 Stitch mockups in `web/design/screens/*.png` are STILL terracotta (deferred — regenerate next Stitch pass); **follow DESIGN.md, not the mockups.**

## Done (11/15) — all pushed

T-001 ingest scaffold · T-003 ranking (`pantryatlas/navigator/ranking.py`) · T-004 API (`pantryatlas/navigator/server.py`, 7 routes) · T-004B design v2 · T-005 Vite+Preact+TS scaffold (`web/`) · T-006 PWA shell · T-007 navigator shell+pantry (`web/src/pages/Navigator.tsx` — the ONE screen) · T-008 recipe section (inline expand, live recompute) · T-009 offline (sw.ts + `web/src/lib/offline-queue.ts` + OfflineBanner) · T-010 ops (systemd unit + bootstrap stage) · T-012 docs (`docs/navigator.md`).

## NEXT — operator approved doing BOTH T-014 and T-002 (in this order after compaction prep)

### T-014 — Gemma 4 vision endpoint (operator: use Gemma 4 E4B multimodal)
- Build `pantryatlas/navigator/vision.py` `parse_shelf(image_bytes, gemma_client) -> list[DetectedIngredient]`.
- Extend `pantryatlas/gemma/client.py` with `vision_generate(image_bytes, prompt, strict=False)` using llama.cpp **multimodal E4B** (operator confirmed E4B is multimodal — do NOT pin a separate model unless E4B genuinely can't do vision; if it can't, surface that and pin a vision GGUF in `docs/gemma4-verified-specs.md`).
- Register `POST /navigator/vision/parse-shelf` in `server.py` → returns `{detected:[{label,confidence}]}`; returns **503 `{error:'vision_unavailable'}`** when the model isn't loaded (the `web/src/components/PhotoReviewSheet.tsx` UI already handles 503/404 gracefully — verified in T-007).
- `tests/navigator/test_vision.py`: (a) mock-gemma unit test asserting JSON parse + repair fallback; (b) `@pytest.mark.pi_integration` live test hitting real Gemma on `tests/fixtures/test-shelf.jpg` (≤500KB veg photo — create it).
- Image preprocessing: resize to model input, EXIF-rotate. Prompt requests structured JSON; parse loop with relaxed-JSON + regex repair (same pattern as `GemmaClient.generate(strict=False)`).
- `docs/gemma4-verified-specs.md`: pin vision model/approach + measured Pi latency for ~1024×768.
- **Live detection is SLOW on Pi (multimodal E4B on CPU) — the mock unit test ships clean; live verify will take minutes.** Don't block the commit on a fast live run.
- Acceptance criteria: see `tasks/prd-navigator.json` T-014 (priority 9.5).

### T-002 — full recipe ingestion (SLOW, ~40-60 min — run in background)
- Extend `pantryatlas.navigator.ingest` to embed each recipe (title+ingredients concat) via `pantryatlas.embeddings.embed` (batched 64), upsert into RecipeStore at `~/.pantryatlas/recipes.db`. Resumable on re-run (skip rows present by recipe id).
- Needs the staged RecipeNLG corpus (`pantryatlas/data/_staging/` — check it exists; T-001/T-007 of v0.1 staged it via the `corbt/all-recipes` HF mirror).
- Kick off as a **background run** (`run_in_background`), then continue other work; produces the real recipe DB that T-011 e2e depends on.
- Acceptance criteria: `tasks/prd-navigator.json` T-002.

### Then: T-011 (e2e, needs T-002's DB) + T-013 (release — **merge to main needs operator sign-off**)

## Execution conventions that worked this session

- **subagent-driven-development:** one implementer subagent (sonnet) per task with a self-contained brief (full task text + which files to read + the cool-Gemini design refs) → I verify criteria MYSELF via Bash (the `feature-dev:code-reviewer` subagent has NO Bash, so it's static-only) → fix-loop if needed → commit + push. Trust-but-verify caught a flaky hash-seed test (T-003) and an import-time DB side-effect (T-004).
- **UI verification:** Chrome MCP is NOT connected on the Pi. Use **headless chromium**: `puppeteer-core` installed at `/tmp/node_modules` driving `/usr/bin/chromium`. `web/mock_backend.py` serves canned API responses for screenshots (avoids slow ONNX startup). For dark mode: `page.emulateMediaFeatures([{name:'prefers-color-scheme',value:'dark'}])`; offline: `page.setOfflineMode(true)`.
- **DON'T** use `agy -p` for MCP tool calls (hangs/deflects). `agy -i` paste-and-run only (Stitch).
- **gitignore gotcha:** the Python `lib/` rule silently ignores `web/src/lib/` — there's now a `!web/src/lib/` un-exclude (gitignore line ~142). Watch for similar collisions.
- `pkill` in Bash caused odd exit 144s — avoid it; target processes specifically or just leave stray local servers.

## Files to read first on resume
1. This file + `~/.claude/.../memory/project_pantryatlas_v0_2_0_in_progress_2026_05_27.md`
2. `tasks/prd-navigator.json` (T-014 + T-002 criteria)
3. `web/design/DESIGN.md` (cool-Gemini single-screen SOT)
4. `pantryatlas/navigator/server.py` + `ranking.py` + `pantryatlas/gemma/client.py` (for T-014)
