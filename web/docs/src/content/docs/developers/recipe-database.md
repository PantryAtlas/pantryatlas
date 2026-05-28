---
title: Recipe database
description: The prebuilt recipe database PantryAtlas ships, where to download it, and how it's versioned.
---

PantryAtlas matches recipes using a prebuilt **recipe database** — a single
SQLite file containing 49,965 recipes plus their search vectors. Building it from
scratch is a multi-hour job on a small computer, so we publish the finished file
and PantryAtlas downloads it for you.

## You don't normally download this yourself

During setup, PantryAtlas fetches the recipe database automatically and checks it
against a published checksum before using it. **Most people never need this
page** — it's here for transparency, for offline or air-gapped installs, and for
contributors building tooling around the artifact.

## Download

The database is hosted as a versioned, immutable file:

- **Database:** <https://dl.pantryatlas.org/db/recipes-v0.2.0.db>
- **Release manifest:** <https://dl.pantryatlas.org/db/recipes-latest.json>
- **Attribution:** <https://dl.pantryatlas.org/db/ATTRIBUTION.txt>

The manifest is the source of truth for the current release. It looks like this:

```json
{
  "db_version": "v0.2.0",
  "schema_version": 1,
  "embedding_model": "bge-m3-int8-onnx",
  "recipe_count": 49965,
  "source": "RecipeNLG",
  "license": "CC-BY-NC-4.0",
  "url": "https://dl.pantryatlas.org/db/recipes-v0.2.0.db",
  "sha256": "8d4be6892d3b5cf39b963227ad2ddbcee5d1157ca0d525ab8f3e14297dfb7c9b",
  "bytes": 237912064
}
```

Always verify the download against the `sha256` in the manifest before using it:

```sh
curl -fL -o recipes.db https://dl.pantryatlas.org/db/recipes-v0.2.0.db
sha256sum recipes.db   # must match the manifest's "sha256"
```

## What's inside

| Field | Value |
| --- | --- |
| Version | v0.2.0 |
| Recipes | 49,965 |
| Size | ~227 MB |
| Embedding model | `bge-m3-int8-onnx` |
| Source corpus | RecipeNLG |
| License | CC-BY-NC-4.0 |

The search vectors are bound to the embedding model named in the manifest.
A database built for one model will not give correct results with another, so the
`embedding_model` and `schema_version` fields travel with every release.

## Versioning

Each release is published under its own immutable URL
(`recipes-v<version>.db`); `recipes-latest.json` always points at the newest one.
A given version is never overwritten, so a pinned URL keeps working.

## License & attribution

Recipe data comes from the public **RecipeNLG** corpus, used under
**CC-BY-NC-4.0**. The attribution notice travels with the artifact at
`ATTRIBUTION.txt`. PantryAtlas is non-commercial and open source; please keep the
attribution intact if you redistribute the database.
