"""T-001 / T-002: Recipe curation + ingestion CLI.

Reads RecipeNLG staged parquet, parses input text into (title, ingredients, instructions)
tuples, applies curation rules (≥3 distinct ingredients, balanced across count buckets 3-5,
6-8, 9+), reports a summary, then embeds and upserts into RecipeStore.

Usage:
    python -m pantryatlas.navigator.ingest --limit 1000 --dry-run
    python -m pantryatlas.navigator.ingest --limit 50000 --target-db ~/.pantryatlas/recipes.db
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import re
import time
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq

log = logging.getLogger(__name__)

# Reused from T-008 (build_vocab.py) patterns
_RE_QUANTITY = re.compile(r"^[\d\s./¼½¾⅓⅔⅕⅖⅗⅘⅙⅚⅛-]+")
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
_RE_PARENS = re.compile(r"\([^)]*\)")
_RE_AFTER_COMMA = re.compile(r",.*$")
_RE_HAS_ALPHA = re.compile(r"[a-z]")
_MAX_LEN = 35

DEFAULT_STAGING = Path(__file__).parent.parent / "data" / "_staging" / "recipenlg.raw.parquet"


def _normalize_ingredient_line(line: str) -> str:
    """Heuristically extract base ingredient name from raw ingredient line.

    Mirrors logic from T-008's build_vocab.py:_normalize_ingredient_line.
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

    # Take before first comma to drop trailing modifiers
    s = _RE_AFTER_COMMA.sub("", s).strip()

    # Collapse interior whitespace
    s = " ".join(s.split())

    return s


def extract_ingredient_lines(text: str) -> list[str]:
    """Parse full recipe text and return cleaned ingredient strings.

    Mirrors logic from T-008's build_vocab.py:extract_ingredient_lines.
    """
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


def parse_recipe(input_text: str) -> dict[str, Any] | None:
    """Parse RecipeNLG-style 'input' field into {title, ingredients, instructions}.

    Returns dict with:
        - title: str (first line, stripped)
        - ingredients: list[str] (normalized ingredient names)
        - instructions: str (full Directions section)

    Returns None if:
        - Cannot extract title (empty first line)
        - Cannot extract ingredients (no Ingredients: block or empty result)
        - Resulting ingredients list is empty after normalization
    """
    if not input_text or not input_text.strip():
        return None

    lines = input_text.strip().split("\n")
    if not lines:
        return None

    # Extract title (first non-empty line)
    title = lines[0].strip()
    if not title:
        return None

    # Extract ingredients
    ingredients = extract_ingredient_lines(input_text)
    if not ingredients:
        return None

    # Extract instructions (Directions section)
    instructions = ""
    if "Directions:" in input_text:
        _, after = input_text.split("Directions:", 1)
        instructions = after.strip()

    return {
        "title": title,
        "ingredients": ingredients,
        "instructions": instructions,
    }


def curate(
    rows: list[dict[str, Any]],
    limit: int,
) -> dict[str, Any]:
    """Curate rows by ingredient-count buckets, aiming for balanced distribution.

    Input: list of {title, ingredients, instructions} dicts
    Output: {
        'selected': list of curated dicts,
        'discarded': list of (reason, count) tuples,
        'buckets': {'3-5': N, '6-8': N, '9+': N}
    }

    Rules:
        - Discard rows with fewer than 3 distinct ingredients
        - Bucket by ingredient count: 3-5, 6-8, 9+
        - Sample to balance: from each bucket, take min(bucket_size, target_per_bucket)
          where target_per_bucket = limit // 3
        - If a bucket is empty after sampling, redistribute leftover
    """
    if not rows:
        return {
            "selected": [],
            "discarded": [("no input rows", 0)],
            "buckets": {"3-5": 0, "6-8": 0, "9+": 0},
        }

    discarded_reasons: dict[str, int] = {}
    buckets: dict[str, list[dict[str, Any]]] = {
        "3-5": [],
        "6-8": [],
        "9+": [],
    }

    # Categorize rows
    for row in rows:
        ing_count = len(row["ingredients"])
        if ing_count < 3:
            discarded_reasons.setdefault("too few ingredients", 0)
            discarded_reasons["too few ingredients"] += 1
            continue

        if 3 <= ing_count <= 5:
            buckets["3-5"].append(row)
        elif 6 <= ing_count <= 8:
            buckets["6-8"].append(row)
        else:  # 9+
            buckets["9+"].append(row)

    # Calculate per-bucket target
    target_per_bucket = limit // 3

    # Sample from each bucket
    selected: list[dict[str, Any]] = []
    for bucket_name in ["3-5", "6-8", "9+"]:
        bucket_rows = buckets[bucket_name]
        take = min(len(bucket_rows), target_per_bucket)
        selected.extend(bucket_rows[:take])

    # If we're short on any bucket, redistribute from others (simple greedy approach)
    current_counts = {
        "3-5": len([r for r in selected if 3 <= len(r["ingredients"]) <= 5]),
        "6-8": len([r for r in selected if 6 <= len(r["ingredients"]) <= 8]),
        "9+": len([r for r in selected if len(r["ingredients"]) >= 9]),
    }

    # Check if any bucket is below 25% of the target (AC-6 requirement)
    # If we have fewer than target_per_bucket in any bucket, try to add more
    for bucket_name in ["3-5", "6-8", "9+"]:
        if current_counts[bucket_name] < target_per_bucket and len(selected) < limit:
            bucket_rows = buckets[bucket_name]
            already_selected = current_counts[bucket_name]
            remaining = list(bucket_rows[already_selected:])
            can_take = min(
                len(remaining),
                limit - len(selected),
                target_per_bucket - already_selected,
            )
            selected.extend(remaining[:can_take])

    # Sort for reproducibility (by title)
    selected.sort(key=lambda r: r["title"])

    # Recount buckets after selection
    final_counts = {
        "3-5": 0,
        "6-8": 0,
        "9+": 0,
    }
    for row in selected:
        ing_count = len(row["ingredients"])
        if 3 <= ing_count <= 5:
            final_counts["3-5"] += 1
        elif 6 <= ing_count <= 8:
            final_counts["6-8"] += 1
        else:
            final_counts["9+"] += 1

    discarded_list = list(discarded_reasons.items())

    return {
        "selected": selected,
        "discarded": discarded_list,
        "buckets": final_counts,
    }


_EMBED_BATCH = 64  # macro-batch size for embed() calls


def _recipe_id(title: str, ingredients: list[str]) -> str:
    """Stable content-addressable ID: SHA-1 of 'title|ing1|ing2|...'."""
    content = title + "|" + "|".join(ingredients)
    return hashlib.sha1(content.encode()).hexdigest()


def _ingest_to_store(selected: list[dict[str, Any]], db_path: Path) -> None:
    """Embed curated recipes and upsert into RecipeStore.

    Steps:
    1. Derive stable recipe IDs for all selected rows.
    2. Query existing IDs from the store; skip already-present rows.
    3. Embed new rows in batches of 64, time it, log throughput.
    4. Upsert Recipe objects into the store.
    """
    # Import here so dry-run path never touches store/embeddings
    from pantryatlas.embeddings import embed  # noqa: PLC0415
    from pantryatlas.store.recipes import Recipe, RecipeStore  # noqa: PLC0415

    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = RecipeStore(db_path)

    try:
        # Derive stable IDs
        id_row_pairs: list[tuple[str, dict[str, Any]]] = []
        for row in selected:
            rid = _recipe_id(row["title"], row["ingredients"])
            id_row_pairs.append((rid, row))

        # Fetch all existing IDs in one query (avoids SQLite IN(?) param-count limits)
        existing_ids: set[str] = {
            r[0]
            for r in store._conn.execute("SELECT id FROM recipes_meta").fetchall()  # noqa: SLF001
        }

        to_embed = [(rid, row) for rid, row in id_row_pairs if rid not in existing_ids]
        n_skipped = len(id_row_pairs) - len(to_embed)

        if n_skipped:
            log.info("skipped: %d already present", n_skipped)

        if not to_embed:
            log.info("Nothing new to embed — all recipes already in store.")
            return

        log.info("Embedding %d new recipes in batches of %d …", len(to_embed), _EMBED_BATCH)

        total_embed_time = 0.0
        total_embedded = 0

        for batch_start in range(0, len(to_embed), _EMBED_BATCH):
            batch_pairs = to_embed[batch_start : batch_start + _EMBED_BATCH]
            texts = [
                row["title"] + " " + " ".join(row["ingredients"])
                for _, row in batch_pairs
            ]

            t0 = time.perf_counter()
            embeddings: np.ndarray = embed(texts)  # (B, 1024) float32 L2-normalised
            total_embed_time += time.perf_counter() - t0
            total_embedded += len(texts)

            batch_recipes = [
                Recipe(
                    id=rid,
                    title=row["title"],
                    language="en",
                    embedding=embeddings[i],
                    ingredients_json=row["ingredients"],
                    instructions=row.get("instructions") or None,
                )
                for i, (rid, row) in enumerate(batch_pairs)
            ]
            store.upsert(batch_recipes)

            if (batch_start // _EMBED_BATCH + 1) % 5 == 0:
                log.info(
                    "  Upserted %d / %d recipes …",
                    batch_start + len(batch_pairs),
                    len(to_embed),
                )

        throughput = total_embedded / total_embed_time if total_embed_time > 0 else 0.0
        log.info("embeddings_throughput_per_sec=%.2f", throughput)
        log.info(
            "Ingestion complete: %d new recipes written, %d skipped.",
            total_embedded,
            n_skipped,
        )

    finally:
        store.close()


def main() -> None:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(prog="pantryatlas.navigator.ingest")
    parser.add_argument("--limit", type=int, required=True,
                        help="Target number of curated recipes to select")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print summary; do not write to DB")
    parser.add_argument(
        "--target-db", type=Path,
        default=Path.home() / ".pantryatlas" / "recipes.db",
        help="Target database path (ignored in dry-run)")
    parser.add_argument("--staging-parquet", type=Path, default=DEFAULT_STAGING,
                        help="Path to RecipeNLG staged parquet")
    args = parser.parse_args()

    log.info("Loading parquet from %s", args.staging_parquet)
    if not args.staging_parquet.exists():
        log.error("Staging parquet not found: %s", args.staging_parquet)
        raise FileNotFoundError(f"Staging parquet not found: {args.staging_parquet}")

    # Phase 1: Load and parse
    # Read up to 4x limit so that even if ~75% of rows discard, we hit the limit
    read_limit = args.limit * 4
    tbl = pq.read_table(args.staging_parquet, columns=["input"])
    tbl = tbl.slice(0, min(read_limit, len(tbl)))

    log.info("Processing %d rows from parquet", len(tbl))

    rows: list[dict[str, Any]] = []
    input_col = tbl.column("input")
    for i, recipe_text in enumerate(input_col.to_pylist()):
        if recipe_text is None:
            continue
        parsed = parse_recipe(recipe_text)
        if parsed:
            rows.append(parsed)
        if (i + 1) % 100_000 == 0:
            log.info("  Processed %d rows, parsed %d recipes so far", i + 1, len(rows))

    log.info("Total recipes parsed: %d", len(rows))

    # Phase 2: Curate
    log.info("Curating to limit=%d", args.limit)
    result = curate(rows[:args.limit * 2], args.limit)  # curate on up to 2x input

    # Phase 3: Report
    print(f"selected: {len(result['selected'])}")
    for reason, count in result["discarded"]:
        print(f"discarded: {count} ({reason})")
    for bucket, count in result["buckets"].items():
        print(f"bucket {bucket}: {count}")

    # Phase 4: Dry-run guard
    if args.dry_run:
        log.info("DRY RUN: no DB writes.")
        return

    # Phase 5: Write path — embed + upsert (T-002)
    _ingest_to_store(result["selected"], args.target_db)


if __name__ == "__main__":
    main()
