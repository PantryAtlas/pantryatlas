# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
