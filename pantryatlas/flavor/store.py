"""FlavorStore — map noisy ingredient phrases to FlavorDB entities and score
flavor cohesion / pantry affinity from shared flavor molecules.

Loads ``pantryatlas/data/compounds.parquet`` (935 FlavorDB food entities, each
with a ``molecules_json`` list of flavor molecules).  Pure + deterministic;
all caches are per-instance so test instances stay isolated.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

_TOKEN_RE = re.compile(r"[a-z']+")

# Generic head-nouns whose preceding modifier usually carries the real food
# identity (e.g. "coconut milk" is coconut-flavored, not dairy).
_GENERIC_HEADS = {"milk", "sauce", "cream", "oil", "juice", "syrup", "powder", "butter"}

# Phrases that must map to NO entity (non-foods or misleading head nouns).
_BLOCKLIST = {"baking soda", "baking powder", "cream of tartar", "corn starch", "cornstarch"}

# Curated phrase (normalized) -> FlavorDB entity name (normalized) fixes.
_ALIASES: dict[str, str] = {}


class FlavorStore:
    def __init__(self, parquet_path: str | Path) -> None:
        df = pd.read_parquet(parquet_path)
        self._ent_mol: dict[int, frozenset[int]] = {}
        self._id2name: dict[int, str] = {}
        self._name2id: dict[str, int] = {}
        rows: list[tuple[str, int]] = []
        for _, r in df.iterrows():
            eid = int(r["compound_id"])
            mols = r["molecules_json"]
            mols = json.loads(mols) if isinstance(mols, str) else mols
            self._ent_mol[eid] = frozenset(
                m["pubchem_id"]
                for m in mols
                if isinstance(m, dict) and m.get("pubchem_id") is not None
            )
            self._id2name[eid] = str(r["compound_name"])
            rows.append((str(r["compound_name"]).strip().lower(), eid))
        # Register longest names first so multiword/specific entities win.
        for name, eid in sorted(rows, key=lambda t: -len(t[0])):
            self._register(name, eid)
            if name.endswith("s"):
                self._register(name[:-1], eid)
        self._jac_cache: dict[tuple[int, int], float] = {}
        self._entity_cache: dict[str, int | None] = {}

    def _register(self, name: str, eid: int) -> None:
        if name and name not in self._name2id:
            self._name2id[name] = eid

    def entity_name(self, eid: int) -> str | None:
        return self._id2name.get(eid)

    # -- matcher ---------------------------------------------------------------
    def entity_for(self, phrase: str) -> int | None:
        key = phrase.strip().lower()
        if key in self._entity_cache:
            return self._entity_cache[key]
        result = self._match(key)
        self._entity_cache[key] = result
        return result

    def _match(self, pl: str) -> int | None:
        if pl in self._name2id:
            return self._name2id[pl]
        if pl in _ALIASES:
            return self._name2id.get(_ALIASES[pl])
        if pl in _BLOCKLIST:
            return None
        words = _TOKEN_RE.findall(pl)
        if not words:
            return None
        n = len(words)
        # longest consecutive token-subsequence (multiword entities first)
        for length in range(min(n, 4), 1, -1):
            for i in range(0, n - length + 1):
                cand = " ".join(words[i : i + length])
                if cand in self._name2id:
                    return self._name2id[cand]
        # head noun, with generic-modifier handling
        head = words[-1]
        if head in _GENERIC_HEADS and n >= 2:
            for w in words[:-1]:
                if w in self._name2id:
                    return self._name2id[w]
        if head in self._name2id:
            return self._name2id[head]
        for w in words:
            if w in self._name2id:
                return self._name2id[w]
        return None

    # -- metrics ---------------------------------------------------------------
    def jaccard(self, e1: int, e2: int) -> float:
        if e1 == e2:
            return 1.0
        key = (e1, e2) if e1 < e2 else (e2, e1)
        cached = self._jac_cache.get(key)
        if cached is not None:
            return cached
        a = self._ent_mol.get(e1, frozenset())
        b = self._ent_mol.get(e2, frozenset())
        union = len(a | b)
        val = (len(a & b) / union) if union else 0.0
        self._jac_cache[key] = val
        return val

    def _entities(self, phrases: list[str]) -> list[int]:
        out: list[int] = []
        for p in phrases:
            e = self.entity_for(p)
            if e is not None and e not in out:
                out.append(e)
        return out

    def cohesion(self, phrases: list[str]) -> float | None:
        ids = self._entities(phrases)
        if len(ids) < 2:
            return None
        total = 0.0
        count = 0
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                total += self.jaccard(ids[i], ids[j])
                count += 1
        return total / count

    def affinity(self, recipe_phrases: list[str], pantry_names: list[str]) -> float | None:
        pantry_entities = {e for e in (self.entity_for(p) for p in pantry_names) if e is not None}
        if not pantry_entities:
            return None
        recipe_entities = self._entities(recipe_phrases)
        non_pantry = [e for e in recipe_entities if e not in pantry_entities]
        if not non_pantry:
            return None
        total = 0.0
        for e in non_pantry:
            total += max(self.jaccard(e, pe) for pe in pantry_entities)
        return total / len(non_pantry)

    def flavor_score(self, recipe_phrases: list[str], pantry_names: list[str]) -> float:
        coh = self.cohesion(recipe_phrases)
        aff = self.affinity(recipe_phrases, pantry_names)
        if coh is None and aff is None:
            return 0.0
        if aff is None:
            return coh  # type: ignore[return-value]
        if coh is None:
            return aff
        return 0.5 * coh + 0.5 * aff
