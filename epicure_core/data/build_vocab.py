"""T-007: Vocab data pull — RecipeNLG + FlavorDB raw artifacts → _staging/.

Downloads raw source data to _staging/ with provenance tracking.
No NER or deduplication — that is T-008's job.

Usage:
    python -m epicure_core.data.build_vocab --stage pull
    python -m epicure_core.data.build_vocab --stage pull --force
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

STAGING_DIR = Path(__file__).parent / "_staging"

# ---------------------------------------------------------------------------
# RecipeNLG (via corbt/all-recipes HuggingFace mirror)
# ---------------------------------------------------------------------------

_RECIPENLG_SHARDS = [
    "https://huggingface.co/datasets/corbt/all-recipes/resolve/main/data/train-00000-of-00004-237b1b1141fdcfa1.parquet",
    "https://huggingface.co/datasets/corbt/all-recipes/resolve/main/data/train-00001-of-00004-d46654ac93566129.parquet",
    "https://huggingface.co/datasets/corbt/all-recipes/resolve/main/data/train-00002-of-00004-3b4f78b99eedadc2.parquet",
    "https://huggingface.co/datasets/corbt/all-recipes/resolve/main/data/train-00003-of-00004-2369b90eb0860a76.parquet",
]

_RECIPENLG_PRIMARY_URL = _RECIPENLG_SHARDS[0]  # recorded in SOURCES.md


def _download_url(url: str, dest: Path, label: str = "") -> None:
    """Stream-download *url* to *dest*, logging progress."""
    tag = label or dest.name
    req = urllib.request.Request(url, headers={"User-Agent": "epicure-core/0.1 T-007"})
    log.info("Downloading %s → %s", tag, dest)
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=120) as resp, dest.open("wb") as fh:
        total = int(resp.getheader("Content-Length") or 0)
        downloaded = 0
        chunk = 1 << 20  # 1 MiB
        while True:
            block = resp.read(chunk)
            if not block:
                break
            fh.write(block)
            downloaded += len(block)
            if total:
                pct = 100 * downloaded / total
                log.info("  %s %.1f%% (%d / %d MB)", tag, pct, downloaded >> 20, total >> 20)
    elapsed = time.monotonic() - t0
    log.info("Downloaded %s in %.1fs (%.1f MB)", tag, elapsed, downloaded / 1e6)


def pull_recipenlg(force: bool = False) -> Path:
    """Download all four corbt/all-recipes shards and concatenate into one raw parquet.

    Output schema: ``id`` (int64), ``input`` (string, full recipe text).
    The raw free-text format is preserved; T-008 parses titles/ingredients.

    Returns the path to ``_staging/recipenlg.raw.parquet``.
    """
    out = STAGING_DIR / "recipenlg.raw.parquet"
    if out.exists() and not force:
        n = pq.read_metadata(out).num_rows
        log.info("recipenlg.raw.parquet already exists (%d rows); skipping (--force to re-pull)", n)
        return out

    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    shard_paths: list[Path] = []

    for i, shard_url in enumerate(_RECIPENLG_SHARDS):
        shard_path = STAGING_DIR / f"_recipenlg_shard{i}.parquet"
        _download_url(shard_url, shard_path, label=f"all-recipes shard {i}")
        shard_paths.append(shard_path)

    log.info("Concatenating %d shards → %s", len(shard_paths), out)
    total_rows = 0
    schema = pa.schema([
        pa.field("id", pa.int64()),
        pa.field("input", pa.string()),
    ])
    row_offset = 0
    with pq.ParquetWriter(out, schema, compression="snappy") as writer:
        for shard_path in shard_paths:
            tbl = pq.read_table(shard_path)
            n = len(tbl)
            ids = pa.array(range(row_offset, row_offset + n), type=pa.int64())
            merged = pa.table({
                "id": ids,
                "input": tbl["input"],
            })
            writer.write_table(merged)
            row_offset += n
            total_rows += n
            log.info("  shard %s: %d rows (running total %d)", shard_path.name, n, total_rows)

    log.info("Cleaning up shard temp files")
    for shard_path in shard_paths:
        shard_path.unlink(missing_ok=True)

    log.info("recipenlg.raw.parquet: %d rows written to %s", total_rows, out)
    return out


# ---------------------------------------------------------------------------
# FlavorDB (via cosylab.iiitd.edu.in live API)
# ---------------------------------------------------------------------------

_FLAVORDB_BASE_URL = "https://cosylab.iiitd.edu.in/flavordb/entities_json?id={id}"
_FLAVORDB_ENTITY_ID_MAX = 1000  # scan 1..1000; paper reports 936 valid entities
_FLAVORDB_WORKERS = 20
_FLAVORDB_RETRIES = 3
_FLAVORDB_BACKOFF = 2.0  # seconds


def _fetch_flavordb_entity(entity_id: int) -> dict | None:
    """Fetch one FlavorDB entity JSON; returns dict or None on 404/error."""
    url = _FLAVORDB_BASE_URL.format(id=entity_id)
    for attempt in range(_FLAVORDB_RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "epicure-core/0.1 T-007"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status == 200:
                    raw = resp.read()
                    try:
                        return json.loads(raw)
                    except json.JSONDecodeError:
                        return None
                elif resp.status == 404:
                    return None
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if attempt < _FLAVORDB_RETRIES - 1:
                time.sleep(_FLAVORDB_BACKOFF * (attempt + 1))
        except Exception:
            if attempt < _FLAVORDB_RETRIES - 1:
                time.sleep(_FLAVORDB_BACKOFF * (attempt + 1))
    return None


def pull_flavordb(force: bool = False) -> Path:
    """Scrape FlavorDB entities 1..1000 via the live ``entities_json`` API.

    Output schema (one row per ingredient/entity):
    - ``entity_id`` (int64)
    - ``category`` (string)
    - ``category_readable`` (string)
    - ``entity_alias`` (string)
    - ``entity_alias_readable`` (string)
    - ``entity_alias_synonyms`` (string)
    - ``natural_source_name`` (string)
    - ``entity_flavor_profile_union`` (string, nullable)
    - ``molecules_json`` (string, JSON-encoded list of molecule dicts)

    Returns the path to ``_staging/flavordb.raw.parquet``.
    """
    out = STAGING_DIR / "flavordb.raw.parquet"
    if out.exists() and not force:
        log.info("flavordb.raw.parquet already exists (%d rows); skipping (use --force to re-pull)",
                 pq.read_metadata(out).num_rows)
        return out

    STAGING_DIR.mkdir(parents=True, exist_ok=True)

    entity_ids = list(range(1, _FLAVORDB_ENTITY_ID_MAX + 1))
    log.info(
        "Fetching FlavorDB entities 1..%d with %d workers",
        _FLAVORDB_ENTITY_ID_MAX,
        _FLAVORDB_WORKERS,
    )
    t0 = time.monotonic()

    records: list[dict] = []
    failed: list[int] = []

    with ThreadPoolExecutor(max_workers=_FLAVORDB_WORKERS) as pool:
        future_to_id = {pool.submit(_fetch_flavordb_entity, eid): eid for eid in entity_ids}
        done_count = 0
        for fut in as_completed(future_to_id):
            eid = future_to_id[fut]
            done_count += 1
            if done_count % 100 == 0:
                elapsed = time.monotonic() - t0
                log.info(
                    "  FlavorDB progress %d/%d (%.0fs elapsed)",
                    done_count, len(entity_ids), elapsed,
                )
            try:
                result = fut.result()
            except Exception as exc:
                log.warning("Entity %d raised exception: %s", eid, exc)
                failed.append(eid)
                continue
            if result is not None:
                records.append(result)

    elapsed = time.monotonic() - t0
    skipped = _FLAVORDB_ENTITY_ID_MAX - len(records) - len(failed)
    log.info(
        "Fetched %d valid FlavorDB entities in %.1fs (%d skipped/404, %d errors)",
        len(records), elapsed, skipped, len(failed),
    )

    if not records:
        raise RuntimeError("FlavorDB: no records fetched — check network/endpoint")

    # Sort by entity_id for reproducibility
    records.sort(key=lambda r: r.get("entity_id", 0))

    def _str(v: object) -> str:
        return "" if v is None else str(v)

    table = pa.table({
        "entity_id": pa.array([r.get("entity_id", 0) for r in records], type=pa.int64()),
        "category": pa.array([_str(r.get("category")) for r in records]),
        "category_readable": pa.array([_str(r.get("category_readable")) for r in records]),
        "entity_alias": pa.array([_str(r.get("entity_alias")) for r in records]),
        "entity_alias_readable": pa.array([_str(r.get("entity_alias_readable")) for r in records]),
        "entity_alias_synonyms": pa.array([_str(r.get("entity_alias_synonyms")) for r in records]),
        "natural_source_name": pa.array([_str(r.get("natural_source_name")) for r in records]),
        "entity_flavor_profile_union": pa.array(
            [_str(r.get("entity_flavor_profile_union")) for r in records]
        ),
        "molecules_json": pa.array([json.dumps(r.get("molecules", [])) for r in records]),
    })

    pq.write_table(table, out, compression="snappy")
    log.info("flavordb.raw.parquet: %d rows written to %s", len(table), out)
    return out


# ---------------------------------------------------------------------------
# SOURCES.md
# ---------------------------------------------------------------------------


def _sha256(p: Path) -> str:
    """Return hex SHA256 of file *p*."""
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def write_sources_md(recipenlg: Path, flavordb: Path) -> None:
    """Write provenance + license info to _staging/SOURCES.md."""
    md = STAGING_DIR / "SOURCES.md"
    rnlg_rows = pq.read_metadata(recipenlg).num_rows
    fdb_rows = pq.read_metadata(flavordb).num_rows
    rnlg_sha = _sha256(recipenlg)
    fdb_sha = _sha256(flavordb)

    text = f"""# Raw vocab sources (T-007 staging)

recipenlg_url: {_RECIPENLG_PRIMARY_URL}
recipenlg_sha256: {rnlg_sha}
recipenlg_rows: {rnlg_rows}
recipenlg_note: All four corbt/all-recipes shards concatenated (shard URLs listed below).
recipenlg_shards:
  - {_RECIPENLG_SHARDS[0]}
  - {_RECIPENLG_SHARDS[1]}
  - {_RECIPENLG_SHARDS[2]}
  - {_RECIPENLG_SHARDS[3]}

flavordb_url: https://cosylab.iiitd.edu.in/flavordb/entities_json?id={{id}}
flavordb_sha256: {fdb_sha}
flavordb_rows: {fdb_rows}
flavordb_note: Scraped from live FlavorDB API, entity IDs 1..{_FLAVORDB_ENTITY_ID_MAX}.

## License

- **RecipeNLG / corbt/all-recipes**: The `corbt/all-recipes` dataset on HuggingFace Hub is a
  community mirror of the RecipeNLG corpus (Bien et al., 2020). The upstream RecipeNLG dataset
  is distributed under **CC-BY-NC-4.0** (Creative Commons Attribution-NonCommercial 4.0
  International). Non-commercial use only; attribution required.
  Original dataset: https://recipenlg.cs.put.poznan.pl/
  Mirror used: https://huggingface.co/datasets/corbt/all-recipes

- **FlavorDB**: FlavorDB (Garg et al., 2018) is provided by the Computational Biology Group,
  IIIT Delhi. It is distributed under the **Creative Commons Attribution-NonCommercial-ShareAlike
  3.0 Unported (CC BY-NC-SA 3.0)** license. Non-commercial use only; attribution required;
  derivatives must share under the same license.
  Source: https://cosylab.iiitd.edu.in/flavordb/
  Paper: https://academic.oup.com/nar/article/doi/10.1093/nar/gkx957/4559748

## Redistribution note

Both datasets are used for derived vocabulary aggregation only. The final
`ingredients.parquet` (T-008 output) does not redistribute recipe text or flavor-compound
relationships — only canonical ingredient name strings extracted from these sources.

The raw parquet files in this `_staging/` directory are **gitignored** and must not be
committed or distributed. Only `SOURCES.md` (this file) is committed to the repository.
"""
    md.write_text(text)
    log.info("SOURCES.md written to %s", md)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="Epicure vocab data pull (T-007)")
    parser.add_argument("--stage", choices=["pull", "emit"], required=True,
                        help="pull = download raw data; emit = T-008 (not implemented here)")
    parser.add_argument("--force", action="store_true",
                        help="Re-download even if output already exists")
    args = parser.parse_args()

    if args.stage == "pull":
        r = pull_recipenlg(force=args.force)
        f = pull_flavordb(force=args.force)
        write_sources_md(r, f)
        print(f"PULL DONE: recipenlg={r} ({pq.read_metadata(r).num_rows} rows), "
              f"flavordb={f} ({pq.read_metadata(f).num_rows} rows)")
    else:
        raise NotImplementedError("--stage emit lands in T-008")


if __name__ == "__main__":
    main()
