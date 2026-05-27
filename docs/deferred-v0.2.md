# Deferred Features for v0.2

These five features are intentionally **not** shipped in v0.1.0. Each requires significant research, design work, or upstream capability that is better deferred until after v0.1 matures in the field.

---

## Mode discovery

**What it is:** Unsupervised clustering of recipes into flavor modes (cuisines, cooking styles, flavor families) using recipe embeddings.

**What v0.1 ships:** The `ModeStore` schema (SQLite table + vec embedding column) and read API (`query_by_vector`). No insert or discovery pipeline.

**Why deferred:** Mode discovery requires a large, diverse corpus of recipes (RecipeNLG alone is ~20k recipes, many partial) and a ground-truth labeling strategy (user feedback, expert-curated labels, or active learning). Rushing the clustering without labeled data risks shipping modes that reflect corpus biases rather than real culinary patterns. v0.2 will include a semi-supervised pipeline (initial k-means seeding + user feedback loop) and a curated set of 20–50 seed modes.

**What v0.2 looks like:**
- Unsupervised embedding-based clustering of recipes
- Semi-supervised refinement via user feedback
- Pre-seeded ~30 cuisine/flavor modes with EN + ES labels
- REST API for mode suggestions given ingredients
- Downstream `mode-atlas` app uses this for recipe filtering

---

## Multilingual vocab

**What it is:** Expansion of ingredient and recipe vocabularies from English-only (v0.1) to EN + ES + VI + ZH + AR.

**What v0.1 ships:** bge-m3 embedding service supporting 100+ languages. Seed data (`IngredientStore`, `RecipeStore`) populated only with English recipes (RecipeNLG) and English ingredient aliases.

**Why deferred:** Multilingual expansion requires:
1. Source data collection (FlavorDB covers compounds, not recipes; sourcing ES/VI/ZH/AR recipes is manual)
2. Translation + back-translation validation (to catch drift)
3. Multilingual fuzzy-match threshold tuning (rapidfuzz ≥0.85 is language-dependent)
4. Schema versioning (current schema doesn't track source language for recipes; needs audit trail)

This work is critical for downstream apps but is better done incrementally with real user feedback on matching quality, not speculatively. v0.2 will start with Spanish (largest overlap with RecipeNLG food domain) and establish the validation pipeline.

**What v0.2 looks like:**
- Recipes in 2+ languages (EN + ES minimum)
- Language-aware fuzzy thresholds in pantry matchers
- Audit trail in schema (source, translator, validation_date)
- Bilingual smoke tests in CI

---

## Audio and photo input

**What it is:** Allow users to upload food photos or speak ingredient lists, with OCR + speech-to-text + visual recognition preprocessing.

**What v0.1 ships:** Text-only ingredient entry (`pantry.resolve` expects a string).

**Why deferred:** This feature touches three separate models:
1. **Photo**: CLIP-based food recognition (e.g., `food-clip`) or fine-tuned ingredient classifier — currently requires >500MB model, no proven accuracy on diverse home cooking photos
2. **Speech**: Whisper (on-device, ~170MB) — reasonable, but requires audio recording + Noise rejection (a Pi-side sidecar)
3. **OCR**: Tesseract or EasyOCR — works but slow on Pi 5 for handwriting

Without upfront field testing (real users, real kitchens, real photos), shipping this risks either shipping an inaccurate model or shipping a slow pipeline. v0.2 will include a modular input layer, starting with speech (lowest friction, Whisper is stable) and deferring photo to v0.3.

**What v0.2 looks like:**
- `pantry.resolve_from_speech(audio_path)` using Whisper
- Intent: "what ingredients do I have?" via voice memo
- Fallback to text if speech confidence < threshold
- Photo pathway (CLIP-based) documented but not implemented

---

## Federation

**What it is:** Allow multiple PantryAtlas instances to share and sync recipe + ingredient data via a git-like merkle tree protocol.

**What v0.1 ships:** Single-instance storage (sqlite-vec at `~/.pantryatlas/`). No sync, no sharing.

**Why deferred:** Federation (offline-first sync with conflict resolution) is architecturally complex:
1. Requires a merkle-tree DAG over the store (recipe + ingredient records must track parent hash + timestamp)
2. Sync protocol must handle concurrent edits (operational transformation or CRDT-like semantics)
3. Community kitchens need conflict UI (which version of the "tomato" recipe do we use?)

This is a natural extension once v0.1 users exist and real sync patterns emerge. Shipped prematurely, it creates technical debt. v0.2 reserves the schema (add `parent_hash`, `timestamp`, `origin_rrn` fields) but no sync implementation.

**What v0.2 looks like:**
- Schema audit trail prepared (parent_hash, timestamp, origin)
- Design doc for sync protocol (CRDT candidate selected)
- Example: two community kitchens share a "borrowed recipes" database

---

## USDA nutritional layer

**What it is:** Attach USDA FoodData Central nutrition facts (calories, protein, fiber, micronutrients, allergens) to each ingredient and recipe.

**What v0.1 ships:** Ingredients and recipes, but no nutrition data.

**Why deferred:** USDA FoodData Central is a 100k+ row CSV. Matching v0.1 ingredient data to USDA entries requires:
1. **Canonical name mapping** (e.g., "tomato" → USDA FDC ID 168107 "Tomatoes, red, ripe, raw")
2. **Portion size inference** (recipes say "2 cups tomatoes"; FDC gives nutrition per 100g — requires conversion)
3. **Allergen + quality flags** (some USDA entries are low-confidence; need user audit)

The mapping is fiddly and error-prone without subject-matter expertise. v0.2 will add the schema + provide a mapping pipeline, but initial deployments will use v0.1 (no nutrition) so users can validate ingredients first.

**What v0.2 looks like:**
- `Ingredient.usda_fdc_id: int | None` field added to schema
- USDA data sidecar (separate CSV or REST service call)
- `ingredient.nutrition(portion_size: str)` → `{"calories": float, "protein": float, ...}`
- Allergen flags (`contains_shellfish`, `contains_tree_nuts`, etc.)

---

## Architectural note: single-package, not multi-repo

PantryAtlas collapses the original 5-repo suite plan (pantry-navigator, slerp-chef, mode-atlas, etc.) into one `pantryatlas` package where sub-products ship as submodules. Deferred items below that were previously "future separate repos" are now "future submodules within `pantryatlas/`." This simplifies dependency management and keeps embedding model + store in one installable unit.

---

## Why defer? Engineering principles applied

**v0.1 ships the minimum that enables downstream apps** (pantry-navigator, slerp-chef, mode-atlas — as future submodules) to function with real users. Each deferred feature is marked with a schema placeholder (e.g., `ModeStore` table exists but has no insert API) so later expansion doesn't require a painful migration.

**Deferral is not avoidance.** Each feature has a design doc, dependency list, and v0.2 milestone. As feedback from community kitchens arrives, prioritization may shift (e.g., speech input might jump ahead if field data shows it's the #1 request).

**Release rhythm:** v0.1 ships Q2 2026. v0.2 roadmap is drafted Q3, with prioritization informed by real-world deployments.

---

## Schema forward-compatibility

The `IngredientStore`, `RecipeStore`, and `ModeStore` schemas are versioned in `pantryatlas/store/migrations/`. Adding deferred features will use SQLite's `ALTER TABLE` migration pattern (add columns, never remove). v0.1 databases upgrade automatically to v0.2 without data loss.

```python
# v0.2 example: adding USDA field
# Before: Ingredient(id, canonical_name, language, aliases, embedding)
# After:  Ingredient(..., usda_fdc_id: int | None)

store = IngredientStore()  # Auto-runs migrations on open
ing = store.get("tomato_001")
print(ing.usda_fdc_id)  # None in v0.1 data, will populate in v0.2
```

---

See [README.md](../README.md) for the v0.1 roadmap and [install-pi5.md](install-pi5.md) to get started.
