"""Tests for T-008: vocab dedupe + emit.

Two tiers:
  - Synthetic pipeline tests (always run): verify pipeline shape on tiny fake data.
  - Real-data slow tests (run only when artifacts exist): validate AC-3/4/5/6 invariants.
"""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

# ---------------------------------------------------------------------------
# Paths to real artifacts (may or may not exist)
# ---------------------------------------------------------------------------

_DATA_DIR = Path(__file__).parent.parent.parent / "pantryatlas" / "data"
_INGREDIENTS_PQ = _DATA_DIR / "ingredients.parquet"
_COMPOUNDS_PQ = _DATA_DIR / "compounds.parquet"
_STAGING_DIR = _DATA_DIR / "_staging"
_FLAVORDB_RAW = _STAGING_DIR / "flavordb.raw.parquet"

_artifacts_exist = _INGREDIENTS_PQ.exists() and _COMPOUNDS_PQ.exists()
_staging_exists = _FLAVORDB_RAW.exists()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_staging(tmpdir: Path) -> tuple[Path, Path]:
    """Write tiny synthetic recipenlg.raw.parquet + flavordb.raw.parquet to tmpdir."""
    staging = tmpdir / "_staging"
    staging.mkdir(parents=True)

    # --- RecipeNLG: 20 fake recipes with 50 distinct ingredient strings ---
    ingredient_sets = [
        ["garlic", "onion", "olive oil", "salt", "pepper"],
        ["garlic", "butter", "flour", "milk", "cheese"],
        ["chicken", "garlic", "lemon juice", "olive oil", "thyme"],
        ["onion", "carrots", "celery", "beef broth", "potatoes"],
        ["sugar", "butter", "flour", "eggs", "vanilla extract"],
        ["tomatoes", "garlic", "basil", "olive oil", "salt"],
        ["rice", "chicken broth", "onion", "garlic", "olive oil"],
        ["ground beef", "onion", "garlic", "tomato sauce", "pasta"],
        ["spinach", "garlic", "olive oil", "lemon juice", "salt"],
        ["mushrooms", "garlic", "butter", "thyme", "cream"],
        ["zucchini", "olive oil", "garlic", "salt", "pepper"],
        ["broccoli", "garlic", "olive oil", "lemon zest", "parmesan"],
        ["salmon", "lemon juice", "dill", "garlic", "butter"],
        ["shrimp", "garlic", "olive oil", "lemon juice", "parsley"],
        ["black beans", "onion", "garlic", "cumin", "lime juice"],
        ["sweet potatoes", "olive oil", "cinnamon", "brown sugar", "butter"],
        ["apples", "sugar", "cinnamon", "butter", "flour"],
        ["bananas", "milk", "eggs", "flour", "baking powder"],
        ["strawberries", "sugar", "lemon juice", "cornstarch", "butter"],
        ["chocolate chips", "butter", "sugar", "eggs", "vanilla extract"],
    ]

    recipes = []
    for i, ings in enumerate(ingredient_sets):
        ing_lines = "\n".join(f"- 1 cup {ing}" for ing in ings)
        text = (
            f"Recipe {i}\n\n"
            f"Ingredients:\n{ing_lines}\n\n"
            f"Directions:\n- Mix and cook."
        )
        recipes.append(text)

    recipe_table = pa.table({
        "id": pa.array(list(range(len(recipes))), type=pa.int64()),
        "input": pa.array(recipes, type=pa.string()),
    })
    pq.write_table(recipe_table, staging / "recipenlg.raw.parquet")

    # --- FlavorDB: 10 fake entities ---
    n = 10
    flavor_table = pa.table({
        "entity_id": pa.array(list(range(1, n + 1)), type=pa.int64()),
        "category": pa.array(["bakery"] * n, type=pa.string()),
        "category_readable": pa.array(["Bakery"] * n, type=pa.string()),
        "entity_alias": pa.array([f"compound-{i}" for i in range(n)], type=pa.string()),
        "entity_alias_readable": pa.array([f"Compound {i}" for i in range(n)], type=pa.string()),
        "entity_alias_synonyms": pa.array([""] * n, type=pa.string()),
        "natural_source_name": pa.array([""] * n, type=pa.string()),
        "entity_flavor_profile_union": pa.array([""] * n, type=pa.string()),
        "molecules_json": pa.array([json.dumps([])] * n, type=pa.string()),
    })
    pq.write_table(flavor_table, staging / "flavordb.raw.parquet")

    return staging, tmpdir


# ---------------------------------------------------------------------------
# Synthetic pipeline tests (always run)
# ---------------------------------------------------------------------------


class TestSyntheticPipeline:
    """Run emit on a tiny synthetic dataset to verify pipeline shape end-to-end."""

    @pytest.fixture(scope="class")
    def emit_artifacts(self, tmp_path_factory):
        """Run emit on synthetic data; return (ingredients_path, compounds_path)."""
        from pantryatlas.data.build_vocab import emit_compounds, emit_ingredients

        tmpdir = tmp_path_factory.mktemp("synthetic_emit")
        staging, out_dir = _make_fake_staging(tmpdir)
        out_dir.mkdir(parents=True, exist_ok=True)

        ing_path = emit_ingredients(
            staging=staging,
            out_dir=out_dir,
            freq_threshold=1,   # accept all in tiny dataset
            top_n_semantic=100,
            fuzzy_threshold=92.0,
            cosine_threshold=0.92,
        )
        cmp_path = emit_compounds(staging=staging, out_dir=out_dir)
        return ing_path, cmp_path

    def test_ingredients_file_exists(self, emit_artifacts):
        ing_path, _ = emit_artifacts
        assert ing_path.exists(), f"ingredients.parquet not created at {ing_path}"

    def test_compounds_file_exists(self, emit_artifacts):
        _, cmp_path = emit_artifacts
        assert cmp_path.exists(), f"compounds.parquet not created at {cmp_path}"

    def test_ingredients_schema(self, emit_artifacts):
        ing_path, _ = emit_artifacts
        schema = pq.read_schema(ing_path)
        assert sorted(schema.names) == ["aliases", "canonical_name", "language", "source"]

    def test_aliases_is_list_type(self, emit_artifacts):
        ing_path, _ = emit_artifacts
        schema = pq.read_schema(ing_path)
        aliases_field = schema.field("aliases")
        assert pa.types.is_list(aliases_field.type), (
            f"aliases must be list<string>, got {aliases_field.type}"
        )

    def test_ingredients_nonzero_rows(self, emit_artifacts):
        ing_path, _ = emit_artifacts
        t = pq.read_table(ing_path)
        assert len(t) > 0, "ingredients.parquet is empty"

    def test_ingredients_canonical_name_nonnull(self, emit_artifacts):
        ing_path, _ = emit_artifacts
        t = pq.read_table(ing_path)
        null_count = t.column("canonical_name").null_count
        assert null_count == 0, f"canonical_name has {null_count} null values"

    def test_ingredients_language_nonnull(self, emit_artifacts):
        ing_path, _ = emit_artifacts
        t = pq.read_table(ing_path)
        null_count = t.column("language").null_count
        assert null_count == 0, f"language has {null_count} null values"

    def test_ingredients_language_is_en(self, emit_artifacts):
        ing_path, _ = emit_artifacts
        t = pq.read_table(ing_path)
        langs = set(t.column("language").to_pylist())
        assert langs == {"en"}, f"unexpected language values: {langs}"

    def test_ingredients_source_is_recipenlg(self, emit_artifacts):
        ing_path, _ = emit_artifacts
        t = pq.read_table(ing_path)
        sources = set(t.column("source").to_pylist())
        assert sources == {"recipenlg"}, f"unexpected source values: {sources}"

    def test_ingredients_canonical_name_unique(self, emit_artifacts):
        ing_path, _ = emit_artifacts
        t = pq.read_table(ing_path)
        names = t.column("canonical_name").to_pylist()
        assert len(names) == len(set(names)), "canonical_name values are not unique"

    def test_compounds_schema(self, emit_artifacts):
        _, cmp_path = emit_artifacts
        schema = pq.read_schema(cmp_path)
        expected = {
            "compound_id", "compound_name", "compound_alias",
            "category", "category_readable", "synonyms",
            "natural_source_name", "flavor_profile", "molecules_json",
        }
        assert set(schema.names) == expected, (
            f"compounds.parquet schema mismatch: got {set(schema.names)}"
        )

    def test_compounds_row_count_matches_staging(self, emit_artifacts, tmp_path_factory):
        """Compounds parquet row count must equal staging FlavorDB row count."""
        _, cmp_path = emit_artifacts
        # Recover staging from the tmpdir embedded in cmp_path
        staging = cmp_path.parent / "_staging"
        staged_n = pq.read_metadata(staging / "flavordb.raw.parquet").num_rows
        emitted_n = pq.read_metadata(cmp_path).num_rows
        assert abs(emitted_n - staged_n) <= 5, (
            f"compounds row count {emitted_n} differs from staged "
            f"FlavorDB {staged_n} by more than ±5"
        )


# ---------------------------------------------------------------------------
# Real-data slow tests (skipped unless artifacts exist)
# ---------------------------------------------------------------------------

_skip_reason = "Real artifacts not present; run --stage emit first"


@pytest.mark.skipif(not _artifacts_exist, reason=_skip_reason)
class TestRealArtifacts:
    """Validate AC-3/4/5/6 invariants on the real emitted parquets."""

    def test_ac3_ingredients_row_count_gte_1500(self):
        """AC-3: ingredients.parquet has >= 1500 rows."""
        n = pq.read_metadata(_INGREDIENTS_PQ).num_rows
        assert n >= 1500, f"ingredients.parquet has only {n} rows (need >= 1500)"

    def test_ac4_ingredients_schema(self):
        """AC-4: ingredients.parquet has exactly [aliases, canonical_name, language, source]."""
        schema = pq.read_schema(_INGREDIENTS_PQ)
        assert sorted(schema.names) == ["aliases", "canonical_name", "language", "source"], (
            f"Schema mismatch: {sorted(schema.names)}"
        )

    def test_ac5_ingredients_canonical_name_unique_nonnull(self):
        """AC-5: canonical_name is unique and non-null; language is non-null."""
        t = pq.read_table(_INGREDIENTS_PQ)
        assert t.column("canonical_name").null_count == 0, "canonical_name has null values"
        assert t.column("language").null_count == 0, "language has null values"
        names = t.column("canonical_name").to_pylist()
        assert len(names) == len(set(names)), "canonical_name values are not unique"

    @pytest.mark.skipif(not _staging_exists, reason="Staging FlavorDB not present")
    def test_ac6_compounds_row_count_near_staged(self):
        """AC-6: compounds.parquet row count within ±5 of staged FlavorDB row count."""
        staged_n = pq.read_metadata(_FLAVORDB_RAW).num_rows
        emitted_n = pq.read_metadata(_COMPOUNDS_PQ).num_rows
        assert abs(emitted_n - staged_n) <= 5, (
            f"compounds row count {emitted_n} differs from staged "
            f"FlavorDB {staged_n} by more than ±5"
        )

    def test_aliases_is_list_string_type(self):
        """aliases column must be list<string> type."""
        schema = pq.read_schema(_INGREDIENTS_PQ)
        aliases_field = schema.field("aliases")
        assert pa.types.is_list(aliases_field.type), (
            f"aliases must be list<string>, got {aliases_field.type}"
        )

    def test_aliases_all_empty_lists(self):
        """v0.1: all aliases values must be empty lists []."""
        t = pq.read_table(_INGREDIENTS_PQ)
        aliases = t.column("aliases").to_pylist()
        non_empty = [a for a in aliases if a]
        assert not non_empty, (
            f"v0.1 aliases should all be []; found {len(non_empty)} non-empty rows"
        )
