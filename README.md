# epicure-core

Foundation package for the **Epicure Suite**: multilingual embeddings (bge-m3), sqlite-vec storage, Gemma 4 lifecycle wrapper, SLERP rotation math, pantry primitives, and Pi-side ops glue.

Targets **Raspberry Pi 5 8GB** running Ubuntu 24.04 LTS or Raspberry Pi OS Bookworm.

## Quick Start

### Install

```bash
python3 -m pip install -e .
```

For development (includes test tools):

```bash
python3 -m pip install -e ".[dev]"
```

### Run Tests

```bash
pytest -q
```

### Code Quality

```bash
ruff check .
```

## Documentation

- **[PRD](tasks/prd-epicure-core.md)** — Product requirements and architecture
- **[Gemma 4 Spec](docs/gemma4-verified-specs.md)** — Verified claims on Gemma 4 capabilities and fallback plans
- **[Install Guide](docs/install-pi5.md)** — Pi bootstrap and environment setup (T-015)
- **[API Reference](docs/api.md)** — Complete public API (T-015)
- **[Deferred Features](docs/deferred-v0.2.md)** — v0.2 roadmap and rationale (T-015)

## Features

### Embeddings (T-003)
Multilingual sentence embeddings via **bge-m3** (int8 ONNX via onnxruntime). Returns `(N, 1024)` float32 unit-norm vectors.

### Storage (T-004)
Three sqlite-vec repos:
- `IngredientStore` — canonical English ingredients with multilingual aliases
- `RecipeStore` — recipes with embedding-based similarity search
- `ModeStore` — schema reserved for v0.2 (mode discovery)

### Gemma 4 (T-010, T-011, T-012)
Context manager lifecycle wrapper around llama.cpp. Auto-selects **E4B** (8GB RAM) or **E2B** (smaller models). Optional relaxed-JSON repair loop with 2-retry limit before raising.

### SLERP Math (T-005)
Pure NumPy spherical linear interpolation for unit vectors. Constrained variant projects to user-defined half-spaces.

### Pantry (T-006)
Ingredient resolution via exact → fuzzy (rapidfuzz ≥0.85) → semantic (bge-m3 cosine ≥0.78).

### Data Pipeline (T-007, T-008)
Pulls RecipeNLG (English recipes) and FlavorDB (flavor compounds). Dedupes by exact + fuzzy + semantic, emits parquet vocab tables.

## Requirements

- Python 3.11+
- numpy ≥2.0
- onnxruntime ≥1.20
- sqlite-vec ≥0.1.6
- rapidfuzz ≥3.10
- pyarrow ≥18.0
- jsonschema ≥4.23
- psutil ≥6.0
- httpx ≥0.27
- fastapi ≥0.115
- uvicorn ≥0.32

For development: pytest, hypothesis, ruff, pytest-asyncio.

## License

Apache License 2.0. See [LICENSE](LICENSE).

## Status

**v0.1.0.dev0** — In development. T-002 (this release) establishes the package scaffold. See [CHANGELOG](CHANGELOG.md) and task tracking in the PRD.
