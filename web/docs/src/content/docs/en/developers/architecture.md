---
title: Architecture overview
description: How PantryAtlas is built, for contributors.
---

PantryAtlas is a **local-first** application: a Python server and a Preact web UI
that run entirely on the small computer in your kitchen. Nothing is sent to a
cloud.

## The pieces

- **Server** (`pantryatlas/`): Python. Serves the web UI and a small HTTP API,
  ranks recipes, and talks to the on-device model.
- **Web UI** (`web/`): Preact + Vite. The Navigator app you use at
  `pantryatlas.local`.
- **Recipe + flavor data:** the public RecipeNLG corpus (CC-BY-NC-4.0) and
  FlavorDB (CC-BY-NC-3.0), stored locally.
- **Model:** a Gemma model runs on-device for vision and language tasks.
- **Inference-provider registry:** lets the device borrow a more capable computer
  on the LAN for heavy work, falling back to the on-board model. See the design
  notes in `docs/superpowers/specs/`.

## Build from source

```bash
git clone https://github.com/PantryAtlas/pantryatlas
cd pantryatlas
pip install -e ".[dev]"
pytest
```

## Contributing

Pull requests are welcome (Apache 2.0). Run `ruff check .` and `pytest` before
opening a PR. Translations: edit the matching file under `web/docs/src/content/`
and open a PR — the "machine-translated" badge links straight to the edit page.
