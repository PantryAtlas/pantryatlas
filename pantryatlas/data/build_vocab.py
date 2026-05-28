"""T-007/T-008: Vocab data pull + dedupe + emit.

T-007: Downloads raw source data to _staging/ with provenance tracking.
T-008: Reads staged artifacts, runs NER heuristic on RecipeNLG ingredient strings,
       dedupes by exact + rapidfuzz(>=0.92) + bge-m3 cosine(>=0.92), emits
       ingredients.parquet and compounds.parquet.

Usage:
    python -m pantryatlas.data.build_vocab --stage pull
    python -m pantryatlas.data.build_vocab --stage pull --force
    python -m pantryatlas.data.build_vocab --stage emit
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

STAGING_DIR = Path(__file__).parent / "_staging"
DATA_DIR = Path(__file__).parent

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
    req = urllib.request.Request(url, headers={"User-Agent": "pantryatlas/0.1 T-007"})
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
            req = urllib.request.Request(url, headers={"User-Agent": "pantryatlas/0.1 T-007"})
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
# T-008: Ingredient string extraction helpers
# ---------------------------------------------------------------------------

# Regex: leading numeric quantity (fractions, decimals, unicode fractions)
_RE_QUANTITY = re.compile(
    r"^[\d\s./¼½¾⅓⅔⅕⅖⅗⅘⅙⅚⅛-]+"
)

# Common measurement units to strip after a leading number
_UNITS = {
    "c", "c.", "cup", "cups",
    "tsp", "tsp.", "teaspoon", "teaspoons",
    "tbsp", "tbsp.", "tablespoon", "tablespoons",
    "oz", "oz.", "ounce", "ounces",
    "lb", "lb.", "lbs", "lbs.", "pound", "pounds",
    "pkg", "pkg.", "package", "packages",
    "can", "cans", "jar", "jars", "carton", "cartons",
    "clove", "cloves", "bunch", "bunches", "head", "heads",
    "sprig", "sprigs", "stalk", "stalks", "slice", "slices",
    "quart", "quarts", "pint", "pints", "gallon", "gallons",
    "ml", "ml.", "l", "liter", "liters", "litre", "litres",
    "g", "g.", "kg", "kg.", "gram", "grams",
    "small", "medium", "large", "extra-large",
    "dash", "pinch", "handful", "drop", "drops",
}

# Parenthetical expressions: (8 oz.), (16 oz.) etc.
_RE_PARENS = re.compile(r"\([^)]*\)")

# Trailing modifiers after comma: ", minced", ", cut up" etc.
# We take only the head before the first comma
_RE_AFTER_COMMA = re.compile(r",.*$")

# Filter: valid ingredient must be alpha-ish (no digits after cleanup)
_RE_HAS_ALPHA = re.compile(r"[a-z]")

# Filter: strings longer than 35 chars are likely parse failures
_MAX_LEN = 35


def _normalize_ingredient_line(line: str) -> str:
    """Heuristically extract the base ingredient name from a raw ingredient line.

    E.g. "2 Tbsp. butter or margarine" -> "butter or margarine" -> "butter"
         "1/2 c. broken nuts (pecans)" -> "broken nuts"
         "1 small jar chipped beef, cut up" -> "chipped beef"
    """
    s = line.strip().lower()
    if not s:
        return ""

    # Remove parentheticals first: "(8 oz.)" etc.
    s = _RE_PARENS.sub("", s).strip()

    # Strip leading quantity
    s = _RE_QUANTITY.sub("", s).strip()

    # Strip leading unit word
    words = s.split()
    if words and words[0] in _UNITS:
        s = " ".join(words[1:]).strip()

    # Some lines have "or" — keep left side only ("butter or margarine" -> "butter")
    # Prefer: take before first comma to drop trailing modifiers
    s = _RE_AFTER_COMMA.sub("", s).strip()

    # Collapse interior whitespace
    s = " ".join(s.split())

    return s


def extract_ingredient_lines(text: str) -> list[str]:
    """Parse full recipe text and return cleaned ingredient strings."""
    # Split on "Ingredients:" section
    if "Ingredients:" not in text:
        return []
    _, after = text.split("Ingredients:", 1)

    # Take only the ingredients block (before Directions)
    if "Directions:" in after:
        after, _ = after.split("Directions:", 1)

    # Lines start with "- " or "\n- "
    raw_lines = [ln.strip().lstrip("- ").strip() for ln in after.split("\n") if ln.strip()]

    results = []
    for raw in raw_lines:
        normalized = _normalize_ingredient_line(raw)
        if not normalized:
            continue
        if not _RE_HAS_ALPHA.search(normalized):
            continue
        if len(normalized) > _MAX_LEN:
            continue
        results.append(normalized)
    return results


# ---------------------------------------------------------------------------
# T-008: Union-Find for connected-component merging
# ---------------------------------------------------------------------------


class _UnionFind:
    """Simple union-find / DSU for integer indices."""

    def __init__(self, n: int) -> None:
        self._parent = list(range(n))
        self._rank = [0] * n

    def find(self, x: int) -> int:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]  # path compression
            x = self._parent[x]
        return x

    def union(self, x: int, y: int) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self._rank[rx] < self._rank[ry]:
            rx, ry = ry, rx
        self._parent[ry] = rx
        if self._rank[rx] == self._rank[ry]:
            self._rank[rx] += 1

    def components(self, freqs: list[int]) -> dict[int, list[int]]:
        """Return {root_idx: [member_idxs]} with highest-freq member as root."""
        groups: dict[int, list[int]] = {}
        for i in range(len(self._parent)):
            r = self.find(i)
            groups.setdefault(r, []).append(i)
        # For each group, elect the member with highest frequency as canonical
        result = {}
        for _r, members in groups.items():
            best = max(members, key=lambda idx: freqs[idx])
            result[best] = members
        return result


# ---------------------------------------------------------------------------
# T-008: emit_ingredients
# ---------------------------------------------------------------------------


def emit_ingredients(
    staging: Path = STAGING_DIR,
    out_dir: Path = DATA_DIR,
    *,
    freq_threshold: int = 5,
    top_n_candidates: int = 5000,
    top_n_semantic: int = 5000,
    fuzzy_threshold: float = 92.0,
    cosine_threshold: float = 0.92,
) -> Path:
    """Dedupe + canonicalize ingredient strings from RecipeNLG.

    Pipeline:
        1. Extract ingredient strings from full recipe text (heuristic NER).
        2. Frequency-rank; discard singletons (freq < freq_threshold).
        3. Exact dedupe (lowercase + whitespace-normalize).
        3b. Cap to top_n_candidates by frequency before O(N²) steps.
        4. Fuzzy dedupe via rapidfuzz (>= fuzzy_threshold) on top-N.
        5. Semantic dedupe via bge-m3 cosine (>= cosine_threshold).
        6. Append low-frequency tail (freq>=freq_threshold, rank>top_n_candidates).
        7. Emit ingredients.parquet.

    Returns path to emitted ingredients.parquet.
    """
    from rapidfuzz import fuzz  # noqa: PLC0415
    from rapidfuzz import process as rfprocess  # noqa: PLC0415

    raw_path = staging / "recipenlg.raw.parquet"
    out = out_dir / "ingredients.parquet"

    log.info("=== emit_ingredients: reading %s ===", raw_path)
    t_start = time.monotonic()

    # ------------------------------------------------------------------
    # Step 1: Extract ingredient strings from all recipes
    # ------------------------------------------------------------------
    t0 = time.monotonic()
    log.info("Step 1: Extracting ingredient lines from 2M+ recipes...")

    counter: Counter = Counter()
    batch_size = 50_000
    tbl = pq.read_table(raw_path, columns=["input"])
    n_recipes = len(tbl)
    log.info("  Total recipes: %d", n_recipes)

    input_col = tbl.column("input")
    for batch_start in range(0, n_recipes, batch_size):
        batch_end = min(batch_start + batch_size, n_recipes)
        batch = input_col.slice(batch_start, batch_end - batch_start).to_pylist()
        for recipe_text in batch:
            if recipe_text is None:
                continue
            lines = extract_ingredient_lines(recipe_text)
            counter.update(lines)
        if (batch_start // batch_size) % 10 == 0:
            log.info(
                "  Processed %d / %d recipes (unique so far: %d)",
                batch_end, n_recipes, len(counter),
            )

    elapsed_extract = time.monotonic() - t0
    log.info(
        "Step 1 done in %.1fs: %d unique raw strings, %d total occurrences",
        elapsed_extract, len(counter), sum(counter.values()),
    )

    # ------------------------------------------------------------------
    # Step 2: Frequency-rank; discard low-frequency strings
    # ------------------------------------------------------------------
    t0 = time.monotonic()
    log.info("Step 2: Frequency filtering (threshold=%d)...", freq_threshold)

    candidates = [(name, freq) for name, freq in counter.items() if freq >= freq_threshold]
    candidates.sort(key=lambda x: -x[1])
    log.info(
        "Step 2: %d candidates after freq>=%d filter (from %d unique)",
        len(candidates), freq_threshold, len(counter),
    )
    elapsed_freq = time.monotonic() - t0

    # ------------------------------------------------------------------
    # Step 3: Exact dedupe (should already be done by Counter, but
    # normalize to be safe: lowercase + collapse whitespace)
    # ------------------------------------------------------------------
    t0 = time.monotonic()
    log.info("Step 3: Exact dedupe...")

    exact_map: dict[str, tuple[str, int]] = {}  # normalized_key -> (best_form, freq)
    for name, freq in candidates:
        key = " ".join(name.lower().split())
        if key not in exact_map or freq > exact_map[key][1]:
            exact_map[key] = (name, freq)

    # Final candidate list after exact dedupe: sorted by freq desc
    exact_candidates = sorted(exact_map.values(), key=lambda x: -x[1])
    n_exact = len(exact_candidates)
    log.info("Step 3: %d unique strings after exact dedupe", n_exact)

    # Step 3b: Cap to top_n_candidates for O(N²) fuzzy+semantic steps.
    # Strings beyond rank top_n_candidates are low-frequency noise and are
    # excluded from the final output (the pipeline contract is fully deduped
    # canonicals; half-processed tail entries violate that).
    top_candidates = exact_candidates[:top_n_candidates]
    names_list = [n for n, _ in top_candidates]
    freqs_list = [f for _, f in top_candidates]
    log.info(
        "Step 3b: Capped to top %d for fuzzy+semantic dedupe (%d excluded below cutoff)",
        len(names_list), n_exact - len(names_list),
    )
    elapsed_exact = time.monotonic() - t0

    # ------------------------------------------------------------------
    # Step 4: Fuzzy dedupe (rapidfuzz >= fuzzy_threshold)
    # ------------------------------------------------------------------
    t0 = time.monotonic()
    n_fuzzy_input = len(names_list)
    log.info(
        "Step 4: Fuzzy dedupe (threshold=%.0f) on %d candidates...",
        fuzzy_threshold, n_fuzzy_input,
    )

    uf = _UnionFind(n_fuzzy_input)

    # Use rapidfuzz cdist for block-based comparison. For large N, do it
    # in blocks of 1000 vs all to avoid excessive memory.
    block_size = 1000
    for i in range(0, n_exact, block_size):
        block = names_list[i : i + block_size]
        # Compare this block against ALL candidates
        scores = rfprocess.cdist(
            block,
            names_list,
            scorer=fuzz.ratio,
            score_cutoff=fuzzy_threshold,
            workers=1,
        )
        # scores shape: (len(block), n_exact); non-zero means >= threshold
        rows, cols = scores.nonzero()
        for r, c in zip(rows, cols, strict=False):
            global_i = i + r
            if global_i != c:
                uf.union(global_i, c)
        if i % 5000 == 0 and i > 0:
            log.info("  Fuzzy dedupe: processed %d / %d", i, n_exact)

    # Collect components: canonical = highest-freq member
    components_fuzzy = uf.components(freqs_list)
    names_fuzzy = list(components_fuzzy.keys())  # indices of canonicals
    n_fuzzy = len(names_fuzzy)
    log.info(
        "Step 4: %d unique strings after fuzzy dedupe (merged %d)",
        n_fuzzy, n_fuzzy_input - n_fuzzy,
    )
    elapsed_fuzzy = time.monotonic() - t0

    # Build reduced lists for semantic step
    fuzzy_names = [names_list[i] for i in names_fuzzy]
    fuzzy_freqs = [freqs_list[i] for i in names_fuzzy]

    # ------------------------------------------------------------------
    # Step 5: Semantic dedupe via bge-m3 cosine (>= cosine_threshold)
    # Limit to top_n_semantic by frequency to bound wall-clock on Pi
    # ------------------------------------------------------------------
    t0 = time.monotonic()

    # Sort by freq descending; take top_n for embedding
    sem_order = sorted(range(len(fuzzy_names)), key=lambda i: -fuzzy_freqs[i])
    sem_names = [fuzzy_names[i] for i in sem_order[:top_n_semantic]]
    sem_freqs = [fuzzy_freqs[i] for i in sem_order[:top_n_semantic]]
    # The tail (if any) is kept as-is — they're low-frequency, unlikely duplicates
    tail_names = [fuzzy_names[i] for i in sem_order[top_n_semantic:]]

    n_sem = len(sem_names)
    log.info(
        "Step 5: Semantic dedupe on top %d candidates (threshold=%.2f)...",
        n_sem, cosine_threshold,
    )

    from pantryatlas.embeddings import embed

    embs = embed(sem_names)  # shape (n_sem, 1024), already L2-normalized
    log.info("  Embeddings done (%d x %d)", *embs.shape)

    # Compute pairwise cosine similarity matrix via matmul (both sides L2-normalized)
    sim_matrix = embs @ embs.T  # (n_sem, n_sem)

    uf2 = _UnionFind(n_sem)
    threshold_f32 = np.float32(cosine_threshold)
    # Only upper triangle (i < j)
    rows, cols = np.where(sim_matrix >= threshold_f32)
    for r, c in zip(rows, cols, strict=False):
        if r < c:
            uf2.union(int(r), int(c))

    components_sem = uf2.components(sem_freqs)
    sem_canonical_indices = list(components_sem.keys())
    n_after_sem = len(sem_canonical_indices)
    log.info(
        "Step 5: %d unique strings after semantic dedupe (merged %d)",
        n_after_sem, n_sem - n_after_sem,
    )
    elapsed_sem = time.monotonic() - t0

    # Final canonical list = semantic-deduped top-N + sem tail (fully processed)
    final_names_raw = [sem_names[i] for i in sem_canonical_indices] + tail_names

    # Safety dedupe: guarantee AC-5 uniqueness (normalize form)
    seen: set[str] = set()
    final_names = []
    for name in final_names_raw:
        key = " ".join(name.lower().split())
        if key not in seen:
            seen.add(key)
            final_names.append(name)

    n_final = len(final_names)
    log.info("Final canonical count: %d", n_final)

    if n_final < 1500:
        log.warning(
            "Only %d canonical ingredients — below 1500 floor. "
            "Consider lowering freq_threshold or raising top_n_semantic.",
            n_final,
        )

    # ------------------------------------------------------------------
    # Step 6: Emit ingredients.parquet
    # ------------------------------------------------------------------
    t0 = time.monotonic()
    log.info("Step 6: Writing ingredients.parquet (%d rows)...", n_final)

    out_dir.mkdir(parents=True, exist_ok=True)

    empty_aliases = pa.array(
        [[] for _ in range(n_final)],
        type=pa.list_(pa.string()),
    )

    table = pa.table({
        "canonical_name": pa.array(final_names, type=pa.string()),
        "language": pa.array(["en"] * n_final, type=pa.string()),
        "aliases": empty_aliases,
        "source": pa.array(["recipenlg"] * n_final, type=pa.string()),
    })

    pq.write_table(table, out, compression="snappy")
    elapsed_emit = time.monotonic() - t0

    elapsed_total = time.monotonic() - t_start
    log.info(
        "emit_ingredients DONE in %.1fs total "
        "(extract=%.1fs, freq=%.1fs, exact=%.1fs, fuzzy=%.1fs, sem=%.1fs, emit=%.1fs). "
        "%d canonical rows → %s",
        elapsed_total,
        elapsed_extract, elapsed_freq, elapsed_exact, elapsed_fuzzy, elapsed_sem, elapsed_emit,
        n_final, out,
    )
    return out


# ---------------------------------------------------------------------------
# T-008: emit_compounds
# ---------------------------------------------------------------------------


def emit_compounds(
    staging: Path = STAGING_DIR,
    out_dir: Path = DATA_DIR,
) -> Path:
    """Mirror FlavorDB raw parquet into compounds.parquet with cleaned column names.

    Output schema:
    - compound_id (int64)
    - compound_name (string) — entity_alias_readable from source
    - compound_alias (string) — entity_alias (slug form)
    - category (string)
    - category_readable (string)
    - synonyms (string)
    - natural_source_name (string)
    - flavor_profile (string)
    - molecules_json (string)

    Row count must be within ±5 of staged FlavorDB (AC-6).

    Returns path to emitted compounds.parquet.
    """
    raw_path = staging / "flavordb.raw.parquet"
    out = out_dir / "compounds.parquet"

    log.info("emit_compounds: reading %s", raw_path)
    t0 = time.monotonic()

    raw = pq.read_table(raw_path)
    n_raw = len(raw)
    log.info("  FlavorDB raw: %d rows", n_raw)

    # Rename columns for clean output schema
    table = pa.table({
        "compound_id": raw.column("entity_id"),
        "compound_name": raw.column("entity_alias_readable"),
        "compound_alias": raw.column("entity_alias"),
        "category": raw.column("category"),
        "category_readable": raw.column("category_readable"),
        "synonyms": raw.column("entity_alias_synonyms"),
        "natural_source_name": raw.column("natural_source_name"),
        "flavor_profile": raw.column("entity_flavor_profile_union"),
        "molecules_json": raw.column("molecules_json"),
    })

    out_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out, compression="snappy")

    elapsed = time.monotonic() - t0
    log.info("emit_compounds DONE in %.1fs: %d rows → %s", elapsed, len(table), out)
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="PantryAtlas vocab data pipeline (T-007/T-008)")
    parser.add_argument("--stage", choices=["pull", "emit"], required=True,
                        help="pull = download raw data; emit = dedupe + emit parquets")
    parser.add_argument("--force", action="store_true",
                        help="Re-download even if output already exists (pull only)")
    args = parser.parse_args()

    if args.stage == "pull":
        r = pull_recipenlg(force=args.force)
        f = pull_flavordb(force=args.force)
        write_sources_md(r, f)
        print(f"PULL DONE: recipenlg={r} ({pq.read_metadata(r).num_rows} rows), "
              f"flavordb={f} ({pq.read_metadata(f).num_rows} rows)")
    elif args.stage == "emit":
        i = emit_ingredients()
        c = emit_compounds()
        i_rows = pq.read_metadata(i).num_rows
        c_rows = pq.read_metadata(c).num_rows
        print(
            f"EMIT DONE: ingredients={i} ({i_rows} rows), "
            f"compounds={c} ({c_rows} rows)"
        )


if __name__ == "__main__":
    main()
