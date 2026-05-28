# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-05-28

The **navigator** submodule: pantry-in → ranked-recipes-out, served as a
single-screen Preact PWA over local Wi-Fi. Built on the v0.1 primitives.

### Added
- **T-004B** Cool-Gemini visual design system (`web/design/DESIGN.md`, `design-system.json`) — single scrolling screen, self-hosted DM Sans, Material 3 tokens holding the Google blue→indigo→purple→magenta gradient.
- **T-001** Recipe ingestion CLI scaffold (`pantryatlas.navigator.ingest`, curation rules + count-bucket balancing, `--dry-run`).
- **T-002** Full recipe ingestion with embeddings → `RecipeStore` (batched bge-m3, SHA-1-resumable upsert). 49,965 recipes embedded into `~/.pantryatlas/recipes.db`.
- **T-003** Pure-Python ranking (`rank_recipes`): `0.50·coverage + 0.20·expiration + 0.20·(1−substitution) + 0.10·cultural_fit`, with a `compute_substitution` fast/refine flag and a batched substitution helper.
- **T-004** FastAPI navigator server (`pantryatlas.navigator.server`) — pantry CRUD + resolve + recipes-from-pantry, lazy store init, same-origin (no permissive CORS), static PWA serving. Responses carry RecipeNLG source attribution (CC-BY-NC-4.0).
- **T-005** Frontend scaffold (Vite 6 + Preact + TypeScript + `@preact/signals`).
- **T-006** PWA shell (manifest, any+maskable icons, hand-rolled service worker, install prompt).
- **T-007** Navigator single screen — shell + pantry section (dual-modality add: type or photograph; mode chip; live debounced resolve).
- **T-008** Navigator single screen — recipe section with coverage rings and inline expand-in-place (no detail sheet, no FAB).
- **T-009** Offline support — service worker (app-shell cache-first, recipes SWR capped-20, pantry network-first) + IndexedDB mutation queue with replay-on-reconnect.
- **T-010** Navigator systemd unit + bootstrap web-build stage.
- **T-011** End-to-end integration test (`tests/integration/test_navigator_e2e.py`, pi_integration) — validated on the real Pi stack: instant 1.04s, refine 1.19s.
- **T-012** Navigator documentation (`docs/navigator.md`, full API reference + ranking algorithm + privacy/attribution).
- **T-014** Gemma 4 vision endpoint (`POST /navigator/vision/parse-shelf`) for shelf-photo ingredient parsing — graceful 503 when the multimodal model isn't loaded; live mmproj wiring is a follow-up.
- **T-013** This release: version bump, CHANGELOG, tag, merge to main.
- **Agentic instant→refine→swaps from-pantry flow.** Because the Pi embedder has a hard ~16-strings/sec floor, `/recipes/from-pantry` runs in **fast mode** (coverage-ranked, no embedding, ~1s) and the client then calls two new endpoints: `POST /recipes/from-pantry/refine` (batches all missing-ingredient embedding in one call and re-ranks) and `POST /recipes/swaps` (lazy per-card substitution suggestions on expand, with a 0.5 cosine floor). The UI paints instantly, shows a "refining…" chip, and re-orders as real substitution scores arrive.

### Changed
- Recipe `instructions` are normalised to a list of step strings at the store boundary (`RecipeStore.iter_overlapping`).
- `rank_recipes` no longer embeds once per candidate; the optional substitution pass batches all unique missing ingredients in a single embedding call.

### Notes
- Fast mode sets `substitution_penalty = 0` (optimistic), so the substitution term contributes a constant `0.20` and does not affect the instant ordering. Refining computes the real penalty, which can only *lower* scores — so cards converge **downward** into a stable settle, never jumping upward.

## [Rebrand] - 2026-05-27

Project renamed from `epicure-core` to `pantryatlas`. Package name, module path,
runtime paths (`~/.pantryatlas/`), systemd units, and ops scripts updated.
Multi-repo suite plan collapsed into one `pantryatlas` package with sub-products
as submodules. Domain: https://pantryatlas.org. Git history preserved.

## [0.1.0] - 2026-05-27

### Added
- **T-001** Gemma 4 spec verification and pinned GGUF (`unsloth/gemma-4-E4B-it-GGUF`)
- **T-002** Package scaffold (pyproject.toml, package layout, Apache 2.0 LICENSE, CI workflow)
- **T-003** bge-m3 multilingual embedding service (in-process + FastAPI sidecar at POST /embed)
- **T-004** sqlite-vec storage layer (IngredientStore + RecipeStore + ModeStore)
- **T-005** SLERP and constrained_slerp utilities (pure NumPy, hypothesis-tested)
- **T-006** Pantry primitives and matchers (exact → fuzzy → semantic resolution)
- **T-007** Vocab data pull (RecipeNLG + FlavorDB raw → _staging/)
- **T-008** Vocab dedupe pipeline (`ingredients.parquet` with 3919 canonical English rows, `compounds.parquet`)
- **T-009** Pi 5 bootstrap script (`ops/pi-bootstrap.sh`, idempotent, ARM64-gated)
- **T-010** GemmaRunner lifecycle (E4B/E2B auto-select, baseline-tps recording)
- **T-011** GemmaClient plain-text generate() via OpenAI-compatible chat endpoint
- **T-012** GemmaClient schema + repair loop (relaxed default, strict opt-in with latency warning)
- **T-013** Memory-pressure monitor + 3 systemd units (gemma, mem-monitor, embeddings)
- **T-014** End-to-end integration smoke test (Pi-gated, opt-in)
- **T-015** Documentation (README, install-pi5, api, deferred-v0.2)
- **T-016** v0.1.0 release prep (this commit)

### Fixed
- License metadata switched to PEP 639 form (`license = "Apache-2.0"`); previous form emitted deprecation warnings on setuptools 77+

### Deferred to v0.2 (see `docs/deferred-v0.2.md`)
- Mode discovery (ICA + GMM unsupervised pipeline)
- Multilingual vocab expansion (XiaChuFang, Povarenok, Tarladalal, Cookpad, Recetas, Yemek, Chefkoch)
- Audio and photo input ingestion
- Federation across multiple Pi instances
- USDA FoodData Central nutritional layer

## [Unreleased]
