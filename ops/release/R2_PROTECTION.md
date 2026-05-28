# R2 download-cost protection posture

The recipe DB and SD card image are public artifacts served from a Cloudflare R2
bucket (`pantryatlas-artifacts`) behind the custom domain `dl.pantryatlas.org`.
This is the runbook for keeping that cheap and abuse-resistant.

## TL;DR — the exposure is small by design

**R2 charges nothing for egress.** Bandwidth out is free at any volume, so the
classic "popular download → surprise bandwidth bill" risk does not exist here.
The only metered things are operations and storage:

| What | Price | Free tier / month |
| --- | --- | --- |
| Egress / bandwidth | **free** | — |
| Class B ops (reads/GET) | $0.36 / million | **10 million** |
| Class A ops (writes/PUT) | $4.50 / million | 1 million |
| Storage | $0.015 / GB-month | **10 GB-month** |

(Current Cloudflare pricing: <https://developers.cloudflare.com/r2/pricing/>.)

The bucket holds a handful of objects totalling ~2.3 GB — under the free storage
tier. Reads are free to 10M/month. Worst-case abuse is bounded to Class B ops: an
attacker would need ~13M extra uncached requests in a month to cost even $1. We are
tending a tip jar, not defending a vault.

## What's already in place (do not regress)

- ✅ **`r2.dev` public URL is DISABLED.** This is the single most important setting.
  The `r2.dev` endpoint bypasses Cloudflare's cache and is a second public door.
  All access goes through `dl.pantryatlas.org`, which is CDN-fronted and cacheable.
- ✅ **Served via the custom domain only** (Cloudflare CDN in front).
- ✅ **Immutable, versioned filenames** (`recipes-v0.2.0.db`, never a mutable
  `latest` blob) — so the edge can cache them effectively forever.

Verify the critical setting anytime:

```bash
wrangler r2 bucket dev-url get pantryatlas-artifacts
# expected: "Public access via the r2.dev URL is disabled."
wrangler r2 bucket domain list pantryatlas-artifacts
# expected: dl.pantryatlas.org — enabled, active
```

## Optional belt-and-suspenders (dashboard only)

None of these are required given the bounded exposure above — they are
defense-in-depth. All need zone-level write access, so they are Cloudflare
**dashboard** steps (not doable with a read-only/wrangler token):

1. **Cache Rule** on `dl.pantryatlas.org` — "Eligible for cache" + a long Edge TTL
   (e.g. 1 month). Makes edge-caching of the immutable artifacts explicit so repeat
   downloads of the DB never touch R2.
   *Caveat:* Cloudflare Free/Pro plans cap cached objects at **512 MB**, so the
   ~1.9 GB `.img.xz` always passes through to R2 (one Class B op + free egress per
   download — fine). The ~227 MB `.db` caches at the edge.
2. **Rate-limiting rule** on `dl.pantryatlas.org/*` — the free plan includes one
   rule. Throttle a single IP hammering the endpoint.
3. **R2 usage notifications** — Cloudflare has no hard spend cap, so set
   billing/usage alerts on Class B ops and storage. This is the real backstop.
4. **(Minor)** bump the custom domain's min TLS version from 1.0 → 1.2.

## Related

- `ops/release/README.md` — how to publish a release artifact.
- `ops/release/publish-db.sh` / `publish-image.sh` — the upload scripts. (The
  ~1.9 GB image exceeds wrangler's ~300 MiB upload limit and is pushed via `rclone`
  against R2's S3 endpoint with multipart.)
