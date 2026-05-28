# pantryatlas API Reference

Complete reference for all public symbols in `pantryatlas` v0.1.0.

## Module overview

```
pantryatlas/
├── embeddings.py          # Multilingual embedding service (bge-m3)
├── store/
│   ├── ingredients.py     # Ingredient database
│   ├── recipes.py         # Recipe database
│   └── modes.py           # Mode database (v0.2)
├── gemma/
│   ├── runner.py          # llama.cpp lifecycle
│   └── client.py          # HTTP client + JSON repair loop
├── geometry/
│   └── slerp.py           # Spherical linear interpolation
├── pantry.py              # Ingredient resolution
└── ops.py                 # (reserved for future ops utilities)
```

---

## Top level

### `pantryatlas.__version__`

**Type:** `str`

The installed version string.

```python
import pantryatlas
print(pantryatlas.__version__)  # '0.1.0.dev0'
```

---

## pantryatlas.embeddings

Multilingual embedding service using bge-m3 (int8 ONNX via onnxruntime).

### `pantryatlas.embeddings.embed`

**Signature:** `embed(texts: list[str]) -> np.ndarray`

**Returns:** `(len(texts), 1024)` float32 ndarray with unit-norm rows (L2-normalized).

Embeds a batch of text strings into a shared vector space (100+ languages). Model is loaded once per process and cached in memory.

```python
from pantryatlas import embeddings

vecs = embeddings.embed(["tomato", "tomate", "tomatillo"])
# Returns shape (3, 1024)

# Cosine similarity
similarity = vecs[0] @ vecs[1]  # ~0.95 (tomato vs tomate)
```

**Performance:** ~1,000 short ingredient strings in <60s on Pi 5.

---

## pantryatlas.store.ingredients

Ingredient database backed by sqlite-vec.

### `pantryatlas.store.ingredients.Ingredient`

**Type:** `dataclass`

Represents a single ingredient with multilingual aliases.

```python
@dataclass
class Ingredient:
    id: str                  # Unique identifier
    canonical_name: str      # English name (English, Tomato)
    language: str           # Language code (en, es, vi, zh, etc.)
    aliases: list[str]      # Multilingual names
    embedding: np.ndarray   # (1024,) unit-norm vector
```

### `pantryatlas.store.ingredients.IngredientStore`

**Signature:** `IngredientStore(db_path: str | None = None) -> IngredientStore`

SQLite-backed ingredient repository. Default path is `~/.pantryatlas/ingredients.db`.

```python
from pantryatlas.store.ingredients import IngredientStore

store = IngredientStore()  # Opens or creates ~/.pantryatlas/ingredients.db

# Upsert ingredients
store.upsert([
    Ingredient(
        id="tomato_001",
        canonical_name="Tomato",
        language="en",
        aliases=["tomato", "tomatoe"],
        embedding=...
    )
])

# Query by vector (top-k nearest neighbors)
results = store.query_by_vector(query_vector, top_k=5, min_cosine=0.7)
# Returns list[Ingredient]

# Get by id
ing = store.get("tomato_001")

# Delete
store.delete("tomato_001")
```

---

## pantryatlas.store.recipes

Recipe database backed by sqlite-vec.

### `pantryatlas.store.recipes.Recipe`

**Type:** `dataclass`

Represents a single recipe with ingredient and instruction text.

```python
@dataclass
class Recipe:
    id: str                      # Unique identifier
    title: str                   # Recipe title
    language: str               # Language code
    ingredients_json: str       # JSON-encoded ingredient list
    instructions: str           # Recipe instructions
    embedding: np.ndarray       # (1024,) vector of recipe content
```

### `pantryatlas.store.recipes.RecipeStore`

**Signature:** `RecipeStore(db_path: str | None = None) -> RecipeStore`

SQLite-backed recipe repository. Default path is `~/.pantryatlas/recipes.db`.

```python
from pantryatlas.store.recipes import RecipeStore

store = RecipeStore()

# Upsert
store.upsert([Recipe(...)])

# Query by vector
results = store.query_by_vector(query_vector, top_k=10)

# Get, delete
recipe = store.get("recipe_001")
store.delete("recipe_001")
```

---

## pantryatlas.store.modes

Mode database (schema reserved for v0.2; no data written in v0.1).

### `pantryatlas.store.modes.Mode`

**Type:** `dataclass`

Represents a cuisine mode or flavor profile.

```python
@dataclass
class Mode:
    id: str                   # Unique identifier
    label_en: str            # English label
    label_local: str         # Localized label
    top_members: list[str]   # Top ingredients in this mode
    embedding: np.ndarray    # (1024,) mode vector
```

### `pantryatlas.store.modes.ModeStore`

**Signature:** `ModeStore(db_path: str | None = None) -> ModeStore`

SQLite-backed mode repository. **No insert API exposed in v0.1**; schema only.

```python
from pantryatlas.store.modes import ModeStore

store = ModeStore()

# Query and read in v0.1
results = store.query_by_vector(query_vector, top_k=5)

# Insert API deferred to v0.2
```

---

## pantryatlas.geometry.slerp

Spherical linear interpolation (SLERP) for unit vectors.

### `pantryatlas.geometry.slerp.slerp`

**Signature:** `slerp(v0: np.ndarray, v1: np.ndarray, t: float) -> np.ndarray`

**Returns:** `(v0.shape[0],)` unit-norm ndarray

Standard spherical linear interpolation between two unit vectors. Interpolates the great-circle arc at parameter `t ∈ [0, 1]`.

```python
from pantryatlas.geometry.slerp import slerp
import numpy as np

v0 = np.array([1, 0, 0], dtype=np.float32)
v1 = np.array([0, 1, 0], dtype=np.float32)

# Midpoint on the great circle
mid = slerp(v0, v1, 0.5)
# Returns unit-norm vector between v0 and v1
```

### `pantryatlas.geometry.slerp.constrained_slerp`

**Signature:** `constrained_slerp(v0: np.ndarray, v1: np.ndarray, t: float, constraint: dict) -> np.ndarray`

**Returns:** `(v0.shape[0],)` unit-norm ndarray

SLERP with half-space constraint. Projects the interpolation to stay within a user-defined half-space (e.g., to enforce semantic constraints on flavor transitions).

```python
from pantryatlas.geometry.slerp import constrained_slerp

# Interpolate but stay on one side of a hyperplane
result = constrained_slerp(
    v0, v1, 0.5,
    constraint={"normal": normal_vector, "offset": 0.0}
)
```

---

## pantryatlas.pantry

Ingredient resolution and matching.

### `pantryatlas.pantry.Ingredient`

**Type:** `dataclass`

High-level ingredient type used by the pantry resolver (distinct from store.ingredients.Ingredient).

```python
@dataclass
class Ingredient:
    id: str
    name: str
    language: str
    aliases: list[str]
```

### `pantryatlas.pantry.Quantity`

**Type:** `dataclass`

Represents an amount of an ingredient.

```python
@dataclass
class Quantity:
    amount: float           # Numeric quantity
    unit: str              # "cup", "g", "ml", "piece", etc.
    ingredient_id: str     # Reference to Ingredient.id
```

### `pantryatlas.pantry.Matcher`

**Type:** `class`

Fuzzy and semantic ingredient matcher.

```python
from pantryatlas.pantry import Matcher

matcher = Matcher(
    exact_threshold=1.0,        # Exact match score
    fuzzy_threshold=0.85,       # rapidfuzz threshold
    semantic_threshold=0.78     # Cosine similarity threshold
)

# Match a user input string
best_match = matcher.match("tomatoe")  # Returns Ingredient
```

### `pantryatlas.pantry.Pantry`

**Type:** `class`

High-level ingredient resolver combining exact, fuzzy, and semantic matching.

```python
from pantryatlas.pantry import Pantry
from pantryatlas.store.ingredients import IngredientStore

pantry = Pantry(store=IngredientStore())

# Resolve a user-input ingredient name
resolved = pantry.resolve("tomatoe")
# Returns Ingredient (best match via exact → fuzzy → semantic pipeline)
```

### `pantryatlas.pantry.resolve`

**Signature:** `resolve(query: str, store: IngredientStore) -> Ingredient | None`

**Returns:** Best-match `Ingredient` or `None` if no match found.

Convenience function for single-ingredient resolution.

```python
from pantryatlas.pantry import resolve
from pantryatlas.store.ingredients import IngredientStore

ing = resolve("tomatoe", store=IngredientStore())
if ing:
    print(f"Resolved to: {ing.canonical_name}")
```

---

## pantryatlas.gemma.runner

Gemma 4 llama.cpp lifecycle management.

### `pantryatlas.gemma.runner.GemmaRunner`

**Type:** `class`

Context manager for llama.cpp subprocess. Auto-selects E4B (8GB) or E2B model based on available RAM.

```python
from pantryatlas.gemma.runner import GemmaRunner

with GemmaRunner() as runner:
    print(runner.is_healthy())  # True if server is responsive
    print(runner.model_tier)     # "E4B" or "E2B"
```

**Attributes:**
- `model_tier: str` — Selected model ("E4B" or "E2B")
- `base_url: str` — llama.cpp server URL (e.g., "http://localhost:12345")

**Methods:**
- `__enter__()` — Starts the llama.cpp subprocess
- `__exit__(exc_type, exc_val, exc_tb)` — Stops the subprocess and cleans up
- `is_healthy() -> bool` — Returns True if server responds within 2s
- `stop()` — Explicitly shut down the subprocess

**Baseline recording:** On first start, writes `~/.pantryatlas/baseline-tps.json` with tokens-per-second benchmark.

### `pantryatlas.gemma.runner.MemoryPressureError`

**Type:** `Exception`

Raised when available RAM is below the minimum required for any Gemma 4 variant (E2B needs ≥4GB; E4B needs ≥6GB).

---

## pantryatlas.gemma.client

HTTP client for llama.cpp with relaxed-JSON repair loop.

### `pantryatlas.gemma.client.GemmaClient`

**Type:** `class`

Python HTTP client for structured and unstructured generation.

```python
from pantryatlas.gemma.client import GemmaClient

client = GemmaClient(base_url="http://localhost:12345")

# Unstructured generation
text = client.generate(
    system="You are a helpful chef.",
    user="What is a good pasta dish?"
)
print(text)  # Plain text response

# Structured generation with schema
result = client.generate(
    system="You are a helpful chef.",
    user="Suggest a recipe.",
    schema={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "ingredients": {"type": "array", "items": {"type": "string"}},
            "instructions": {"type": "string"}
        },
        "required": ["title", "ingredients", "instructions"]
    }
)
print(result)  # dict matching schema
```

**Signature:** `generate(system: str, user: str, schema: dict | None = None, strict: bool = False) -> str | dict`

**Parameters:**
- `system: str` — System prompt (role, context, instructions)
- `user: str` — User message
- `schema: dict | None` — JSON Schema dict. If provided, output is validated and repaired (default behavior).
- `strict: bool` — If True, use llama.cpp grammar-constrained mode. **Warning:** ~6 min/batch latency observed. Default: False (relaxed mode).

**Returns:**
- `str` if schema is None
- `dict` if schema is provided and output validates

**Repair loop:** If the model's first attempt fails validation, the client retries with a repair prompt (up to 2 times) before raising `RepairExhaustedError`.

### `pantryatlas.gemma.client.RepairExhaustedError`

**Type:** `Exception`

Raised when the model fails to produce valid JSON after 2 repair attempts.

```python
from pantryatlas.gemma.client import GemmaClient, RepairExhaustedError

client = GemmaClient()

try:
    result = client.generate(system=..., user=..., schema=...)
except RepairExhaustedError as e:
    print(f"Model could not repair JSON: {e}")
```

---

## pantryatlas.ops

Reserved namespace for operations utilities (memory monitor, systemd integration, logging). No public exports in v0.1.

---

## Common patterns

### Embedding + search workflow

```python
from pantryatlas import embeddings
from pantryatlas.store.ingredients import IngredientStore

# Load store
store = IngredientStore()

# Embed a query
query_text = "red vegetable"
query_vec = embeddings.embed([query_text])[0]

# Find similar ingredients
results = store.query_by_vector(query_vec, top_k=5)
for ing in results:
    print(f"{ing.canonical_name} (similarity: {...})")
```

### Multi-language ingredient resolution

```python
from pantryatlas.pantry import resolve
from pantryatlas.store.ingredients import IngredientStore

store = IngredientStore()

# English
ing_en = resolve("tomato", store)

# Spanish
ing_es = resolve("tomate", store)

# Vietnamese
ing_vi = resolve("cà chua", store)

# All resolve to the same ingredient (if seed data includes aliases)
```

### Structured Gemma output

```python
from pantryatlas.gemma.runner import GemmaRunner
from pantryatlas.gemma.client import GemmaClient

with GemmaRunner():
    client = GemmaClient()
    
    recipe = client.generate(
        system="You are a recipe author. Respond in valid JSON.",
        user="Create a simple tomato soup recipe.",
        schema={
            "title": {"type": "string"},
            "servings": {"type": "integer"},
            "ingredients": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "item": {"type": "string"},
                        "amount": {"type": "number"},
                        "unit": {"type": "string"}
                    }
                }
            },
            "steps": {"type": "array", "items": {"type": "string"}}
        }
    )
    
    print(f"Recipe: {recipe['title']}")
    print(f"Servings: {recipe['servings']}")
    for ing in recipe['ingredients']:
        print(f"  - {ing['amount']} {ing['unit']} {ing['item']}")
```

---

## See also

- **[Installation Guide](install-pi5.md)** — How to set up on Pi 5
- **[Deferred Features](deferred-v0.2.md)** — What's coming in v0.2
- **[Gemma 4 Spec](gemma4-verified-specs.md)** — Verified capability claims
- **[GitHub](https://github.com/pantryatlas/pantryatlas)** — Source code and issues
