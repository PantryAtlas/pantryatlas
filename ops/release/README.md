# Releasing the recipe DB artifact

The prebuilt recipe DB is published to Cloudflare R2 and fetched by
`ops/pi-bootstrap.sh`. CI does **not** rebuild the DB — it is built once on a Pi
(the ~5.2h ingest) and uploaded with this runbook.

## One-time setup

1. `npx -y wrangler r2 bucket create pantryatlas-artifacts`
2. Confirm write access (OAuth or an R2-scoped `CLOUDFLARE_API_TOKEN`):
   `echo hi > /tmp/hc.txt && npx -y wrangler r2 object put pantryatlas-artifacts/healthcheck.txt --file /tmp/hc.txt --remote`
   then `npx -y wrangler r2 object delete pantryatlas-artifacts/healthcheck.txt --remote`.
3. **Dashboard step (wrangler can't do this):** attach `dl.pantryatlas.org` to the
   bucket (R2 → bucket → Settings → Custom Domains). Until DNS is live, enable the
   managed `r2.dev` URL and use that in the bootstrap pins.

## Each release

From a machine with the built DB present (system `python3` must be able to import
`pantryatlas` — run from the repo root, or `pip install -e .` first):

```bash
ops/release/publish-db.sh ~/.pantryatlas/recipes.db v0.2.0
```

This stamps the DB (`PRAGMA user_version` + `_pantryatlas_db_meta`), uploads the
`.db`, the per-version + `latest` manifests, and `ATTRIBUTION.txt`, then prints:

```
RECIPES_DB_URL="https://dl.pantryatlas.org/db/recipes-v0.2.0.db"
RECIPES_DB_SHA256="<sha>"
```

Paste those two lines into the pins in `ops/pi-bootstrap.sh` and commit. Dry-run
first with `PUBLISH_DRY_RUN=1 ops/release/publish-db.sh ...` to preview uploads.

Then verify live: `PANTRYATLAS_PI_INTEGRATION=1 pytest tests/integration/test_recipes_db_artifact.py -m pi_integration -v`.
