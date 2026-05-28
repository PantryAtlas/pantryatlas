# PantryAtlas

**One package for multilingual food intelligence on the edge** — multilingual embeddings, sqlite-vec storage, Gemma 4 lifecycle wrapper, SLERP rotation math, pantry primitives, and Pi-side ops glue. Sub-products ship as submodules within this single package. Runs on **Raspberry Pi 5** with ≥2GB headroom for downstream applications.

Domain: https://pantryatlas.org

## Quick Start

Bootstrap a fresh **Pi 5 running Raspberry Pi OS Bookworm 64-bit**:

```bash
git clone https://github.com/PantryAtlas/pantryatlas.git ~/pantryatlas
bash ~/pantryatlas/ops/pi-bootstrap.sh
# ~30 min later: "BOOTSTRAP COMPLETE"
```

> Bootstrap now also downloads the prebuilt recipe database (~227 MB, sha256-verified)
> into `~/.pantryatlas/recipes.db` — no multi-hour local ingest required.

Then in Python:

```python
from pantryatlas import embeddings, pantry, gemma
from pantryatlas.store import ingredients

# Multilingual embeddings
vecs = embeddings.embed(["tomato", "tomate", "tomatillo"])

# Ingredient resolution (exact → fuzzy → semantic)
resolved = pantry.resolve("tomatoe", store=ingredients.IngredientStore())

# Gemma 4 with relaxed-JSON repair (2-retry loop)
with gemma.runner.GemmaRunner() as runner:
    client = gemma.client.GemmaClient()
    result = client.generate(
        system="You are a chef.",
        user="Suggest a recipe for tomatoes.",
        schema={"title": "str", "ingredients": ["str"]}
    )
```

## Documentation

- **[Installation Guide](docs/install-pi5.md)** — Step-by-step Pi 5 setup (for community kitchens)
- **[API Reference](docs/api.md)** — Complete public API reference
- **[Navigator](docs/navigator.md)** — v0.2.0 pantry-in → ranked-recipes-out submodule (API reference, ranking algorithm, ingestion CLI, PWA install)
- **[Deferred Features](docs/deferred-v0.2.md)** — What's coming in v0.2 and why
- **[Gemma 4 Spec](docs/gemma4-verified-specs.md)** — Verified capability claims with sources
- **[Full PRD](tasks/prd-pantryatlas.md)** — Product requirements and architecture

## What's new in v0.2.0 — the Navigator

The **navigator** submodule turns the v0.1 primitives into an end-user app:
**pantry-in → ranked-recipes-out**, served as a single-screen Preact PWA over
your local Wi-Fi (open `pantryatlas.local` on any device). No cloud, no account.

- **49,965 recipes** matched on-device against what's in your pantry, ranked by
  `0.50·coverage + 0.20·expiration + 0.20·(1−substitution) + 0.10·cultural_fit`.
- **Instant → refine → swaps** flow tuned to the Pi's embedding budget: the screen
  paints coverage-ranked results in ~1s (no embedding), then a background pass
  batches the real substitution scores and re-orders, and per-card ingredient
  swaps load lazily on expand.
- **Dual-modality input** — type an ingredient or photograph your shelf (Gemma 4
  vision parses it; degrades gracefully when the multimodal model isn't loaded).
- **Offline-first** — service worker + IndexedDB mutation queue that replays on
  reconnect.
- **Prebuilt recipe database** (~227 MB, sha256-verified) fetched automatically on
  first boot, so there's no multi-hour local ingest. See the
  [recipe-database docs](https://docs.pantryatlas.org/developers/recipe-database/).
- **One-flash SD card image** — write `pantryatlas-v0.2.0.img.xz` to a card and go.
  See [Download & flash](https://docs.pantryatlas.org/setup/install-image/).

Full detail: [Navigator docs](docs/navigator.md) · [CHANGELOG](CHANGELOG.md).

## The v0.1.0 foundation

### Embeddings
Multilingual sentence embeddings via **bge-m3** (int8 ONNX). Returns `(N, 1024)` unit-norm float32 vectors. Supports 100+ languages; tested on English, Vietnamese, Chinese, Spanish, and Arabic.

### Storage
Three sqlite-vec repositories:
- **IngredientStore** — canonical English ingredients + multilingual aliases
- **RecipeStore** — recipes with vector-based similarity search
- **ModeStore** — schema reserved; no data written in v0.1

### Gemma 4 Lifecycle
Python wrapper around llama.cpp. Auto-picks E4B (8GB) or E2B model based on available RAM. Includes optional relaxed-JSON repair loop (up to 2 retries) instead of grammar-constrained mode.

### SLERP Math
Pure NumPy spherical linear interpolation. Standard and constrained (half-space projection) variants.

### Pantry
Ingredient resolution: exact match → fuzzy (rapidfuzz ≥0.85) → semantic (cosine ≥0.78).

### Data Pipeline
Pulls RecipeNLG (English recipes) and FlavorDB (flavor compounds), dedupes by exact+fuzzy+semantic, emits parquet vocabulary.

## Install for Development

```bash
python3 -m pip install -e ".[dev]"
pytest -q
ruff check .
```

## Requirements

- Python 3.11+
- Raspberry Pi 5 8GB (or any ARM64 system with ≥6GB free RAM for E4B, ≥4GB for E2B)
- Core: numpy, onnxruntime, sqlite-vec, rapidfuzz, pyarrow, jsonschema, psutil
- Gemma runner: httpx
- Optional FastAPI sidecar: fastapi, uvicorn

See `pyproject.toml` for pinned versions.

## License

Apache License 2.0. See [LICENSE](LICENSE).

## Status

**v0.2.0** — the navigator app ships on top of the v0.1 primitives (pantry-in →
ranked-recipes-out PWA, prebuilt recipe DB, one-flash SD image). See
[CHANGELOG](CHANGELOG.md) for the full history. Next: live Gemma vision (mmproj),
metadata-filtered vector search, mode discovery, multilingual vocab, USDA
nutritional data.
