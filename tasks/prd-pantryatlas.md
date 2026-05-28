> **⚠️ Task numbering was reorganized for execution.**
> This prose PRD numbers tasks T-001..T-014 in spec order.
> For execution, see `/home/craigm26/pantryatlas/tasks/prd.json` which renumbers them T-001..T-016 in dependency-respecting order (and splits two tasks).
> **`prd.json` is authoritative for all task references in code, commits, and docs.**

# PRD: `pantryatlas` v0.1.0

> Foundation package for PantryAtlas. Every downstream submodule (`pantry-navigator`, `slerp-chef`, `mode-atlas`, `pantryatlas-mcp`) depends on this.

## 1. Introduction / Overview

`pantryatlas` is the shared Python package that ships the primitives the rest of the PantryAtlas is built from: a multilingual embedding service (`bge-m3`), a sqlite-vec storage layer, a Gemma 4 lifecycle wrapper (E4B with E2B fallback), SLERP rotation math, pantry types + matchers, and the Pi-side ops glue (bootstrap script, systemd units, memory-pressure gate). It targets a Raspberry Pi 5 8GB running Ubuntu 24.04 LTS or Raspberry Pi OS Bookworm.

It is **library-only** for v0.1.0 — no user-facing app, no REST endpoints. Downstream apps consume `pantryatlas` as a dependency.

## 2. Goals

- Provide a single `pip install -e .` path that works on a clean Pi 5 8GB in <30 min via `pi-bootstrap.sh`.
- Ship multilingual embeddings that let Vietnamese, Chinese, Spanish, and English ingredient strings co-locate in vector space.
- Make Gemma 4 cheap and predictable to call from Python, with structured output that does not pay the ~6-min/batch strict-JSON tax observed in `local-llm-ops` T9.
- Ship SLERP math (standard + constrained) that exactly matches a reference NumPy implementation.
- Give downstream repos a stable storage API (`IngredientStore`, `RecipeStore`, `ModeStore`) backed by sqlite-vec.
- Stay within a Pi 5 8GB RAM envelope that leaves ≥2GB headroom for downstream apps.
- Document Gemma 4 spec claims with sources (or mark them unverified) before they become load-bearing.

## 3. Tasks

### T-001: Verify Gemma 4 spec claims (research only)
**Description:** The prose plan asserts Gemma 4 has 256K context, 140+ language support, E4B vision input, E2B/E4B audio input, and native system-prompt support. These claims must be confirmed against primary sources (Google AI / DeepMind model card, llama.cpp release notes, HuggingFace model page) before downstream design depends on them. Produce a short artifact at `docs/gemma4-verified-specs.md` listing each claim with a verified value, a citation URL, and a verified/unverified flag.

**Acceptance Criteria:**
- [ ] `docs/gemma4-verified-specs.md` exists
- [ ] Each of the 5 claims (context length, language count, E4B vision, audio modalities, native system prompt) has either a confirmed value + source URL, or is marked `UNVERIFIED — fallback plan: <plan>`
- [ ] If any claim is wrong, the affected design decisions are listed (e.g. "if no native system prompt, the runner abstraction needs a role-prefix shim")
- [ ] Decision logged: which Gemma 4 GGUF build to pin (e.g. `gemma-4-e4b-q4_k_m.gguf` from a specific upstream release)

### T-002: Project scaffold
**Description:** Stand up the `pantryatlas` Python package layout: `pyproject.toml` (PEP 621, Apache 2.0, deps pinned at floor versions), package skeleton matching the architecture sketch in the plan, `LICENSE` (Apache 2.0), `README.md` (one-page quickstart), `CHANGELOG.md`, `.gitignore`, and GitHub Actions CI stub running `ruff` + `pytest` on Linux ARM64 (or `linux-aarch64` self-hosted if available; otherwise document the gap).

**Acceptance Criteria:**
- [ ] `pip install -e .` succeeds from clean venv on Pi 5 (Bookworm, Python 3.11+)
- [ ] `python -c "import pantryatlas; print(pantryatlas.__version__)"` prints `0.1.0.dev0`
- [ ] Package layout matches the plan: `pantryatlas/{embeddings,store,gemma,geometry,pantry,data}/`
- [ ] `LICENSE` is Apache 2.0 (matches Gemma 4)
- [ ] CI workflow runs `ruff check` + `pytest -q` on push (even if some tests are placeholders)
- [ ] Quality checks pass

### T-003: Pi bootstrap script
**Description:** Write `ops/pi-bootstrap.sh` — a single idempotent script that takes a fresh Pi 5 running Bookworm and gets it to "smoke test ready": installs apt deps (build-essential, cmake, git, python3-venv, sqlite3), creates a Python venv at `~/pantryatlas/venv`, clones + builds llama.cpp from a pinned commit with ARM64-tuned flags (`-DLLAMA_NATIVE=ON -DGGML_LLAMAFILE=ON` plus Gemma 4 hybrid-attention flags as confirmed in T-001), downloads the chosen Gemma 4 GGUF, and installs `pantryatlas` in editable mode. Logs each step; re-running is a no-op.

**Acceptance Criteria:**
- [ ] Running `bash ops/pi-bootstrap.sh` on a clean Pi 5 Bookworm reaches "BOOTSTRAP COMPLETE" in <30 min
- [ ] Re-running the script is idempotent (no errors, ≤1 min)
- [ ] llama.cpp commit SHA is pinned in the script (not `main`)
- [ ] Gemma 4 GGUF URL + SHA256 are pinned and verified post-download
- [ ] On a machine that is not ARM64, the script exits with a clear error message instead of producing a broken build
- [ ] Quality checks pass

### T-004: Gemma 4 runner (llama.cpp lifecycle)
**Description:** `pantryatlas/gemma/runner.py` manages the llama.cpp server subprocess: starts it on a free port, picks the E4B model if `psutil.virtual_memory().available >= 6 GiB` else E2B, exposes `start()`, `stop()`, `is_healthy()`, and a context manager. Records baseline tokens/sec on first start to `~/.pantryatlas/baseline-tps.json`. Frees memory between heavy jobs by tearing down the subprocess when explicitly asked.

**Acceptance Criteria:**
- [ ] `GemmaRunner().__enter__()` brings up llama.cpp and `__exit__()` shuts it down cleanly (no orphan processes)
- [ ] Auto-select picks E4B on an idle Pi 5 8GB, E2B if free RAM <6GiB (testable by mocking `psutil.virtual_memory`)
- [ ] First start writes `baseline-tps.json` with `{ "tokens_per_second": float, "model": "E4B"|"E2B", "timestamp": iso8601 }`
- [ ] `is_healthy()` returns False if the subprocess died or fails to respond within 2s
- [ ] Quality checks pass

### T-005: Gemma 4 client (relaxed-JSON + repair)
**Description:** `pantryatlas/gemma/client.py` is the Python HTTP client that talks to the running llama.cpp server. Exposes `generate(system: str, user: str, schema: dict | None = None, strict: bool = False) -> str | dict`. Default path is **relaxed**: when `schema` is provided, prompt-instruct the model with the schema and run a `jsonschema` validate + repair-loop (max 2 retries) against the output. Strict grammar-constrained mode is opt-in only via `strict=True`, with a docstring warning citing the ~6-min/batch latency observed in `local-llm-ops` T9.

**Acceptance Criteria:**
- [ ] `generate(system, user)` returns plain text from a live Gemma 4 instance
- [ ] `generate(system, user, schema=schema)` returns a dict that validates against `schema`
- [ ] When the model's first attempt fails validation, the client retries with a repair prompt up to 2 times before raising
- [ ] `strict=True` invokes llama.cpp grammar files; docstring + CHANGELOG warn about latency
- [ ] Unit tests use a fake server fixture (no live model required for CI)
- [ ] Quality checks pass

### T-006: bge-m3 embedding service
**Description:** `pantryatlas/embeddings.py` wraps `bge-m3` int8 ONNX via `onnxruntime`. Exposes a single `embed(texts: list[str]) -> np.ndarray` returning `(len(texts), 1024)` float32 normalized vectors. Loads the model once per process. Includes a thin optional FastAPI sidecar (`pantryatlas/embeddings/server.py`) that exposes the same API over HTTP for cross-process access without per-process model reload.

**Acceptance Criteria:**
- [ ] `embed(["tomato", "tomate", "tomatillo"])` returns a `(3, 1024)` float32 ndarray with unit-norm rows
- [ ] Cosine similarity between `"eggplant"` and `"aubergine"` ≥ 0.85 (smoke check on multilingual behavior)
- [ ] FastAPI sidecar `POST /embed {"texts": [...]}` returns the same vectors as the in-process call
- [ ] Embedding 1,000 short ingredient strings completes in <60s on Pi 5 (benchmark recorded)
- [ ] Quality checks pass

### T-007: sqlite-vec storage layer
**Description:** `pantryatlas/store/{ingredients,recipes,modes}.py` implements three thin repos backed by sqlite-vec. Schemas: `ingredients(id, canonical_name, language, aliases JSON, embedding vec(1024))`, `recipes(id, title, language, ingredients_json, instructions, embedding vec(1024))`, `modes(id, label_en, label_local, top_members JSON, embedding vec(1024))`. Each repo exposes `upsert`, `get`, `query_by_vector(top_k, filters)`, `delete`. `ModeStore` ships but no data is written to it in v0.1.0 (mode discovery is deferred to v0.2).

**Acceptance Criteria:**
- [ ] All three stores create their tables idempotently on first open
- [ ] `IngredientStore.upsert([...])` then `query_by_vector(v, top_k=5)` returns the 5 nearest by cosine
- [ ] Round-trip survives `db.close()` and reopen (data persists)
- [ ] Total DB file size with the v0.1 vocab loaded is <500MB
- [ ] `ModeStore` is documented as "schema reserved for v0.2" with no insert path called yet
- [ ] Quality checks pass

### T-008: SLERP utilities (standard + constrained)
**Description:** `pantryatlas/geometry/slerp.py` implements `slerp(a: ndarray, b: ndarray, t: float) -> ndarray` (handles the `dot ≈ 1` short-circuit case correctly) and `constrained_slerp(a, b, t, mode_basis) -> ndarray` that rotates from a toward b but projects the result to stay within the half-space defined by `mode_basis` (the constraint mode pole). Pure NumPy. Property tests with `hypothesis` checking unit-norm preservation, endpoint identity (`slerp(a,b,0)==a`, `slerp(a,b,1)==b`), and parity with a reference implementation.

**Acceptance Criteria:**
- [ ] `slerp` matches a reference NumPy implementation to 1e-6 across 1000 random unit-vector pairs
- [ ] `slerp(a, a, 0.5)` returns `a` (no NaN from acos(1))
- [ ] Result of `slerp` always has `||result|| ≈ 1` (within 1e-6)
- [ ] `constrained_slerp(a, b, t, mode_basis)` result has `mode_basis @ result >= mode_basis @ a` (stays inside or moves further into the mode)
- [ ] `hypothesis` property tests included
- [ ] Quality checks pass

### T-009: Pantry primitives + matchers
**Description:** `pantryatlas/pantry/{models,matcher}.py`. `Pantry` is a dataclass holding `list[Ingredient]`; `Ingredient` has `canonical_name`, `raw_text`, `quantity: Quantity | None`, `expires_at: date | None`. Matchers: `exact_match(raw, vocab)`, `fuzzy_match(raw, vocab, threshold=0.85)` using rapidfuzz, `semantic_match(raw, vocab, embedder, threshold=0.78)` using bge-m3 cosine. `resolve(raw_text) -> Ingredient | None` runs exact → fuzzy → semantic in that order.

**Acceptance Criteria:**
- [ ] `resolve("old garlic")` returns the `garlic` canonical ingredient (fuzzy path)
- [ ] `resolve("courgette")` returns the `zucchini` canonical ingredient (semantic path, no alias table entry needed)
- [ ] `resolve("xyzzyplant")` returns None
- [ ] `Pantry.add(Ingredient)` and `Pantry.remove(canonical_name)` maintain uniqueness by canonical_name
- [ ] Expiration-aware iteration: `pantry.expiring_within(days=2)` returns ingredients with `expires_at <= today + 2`
- [ ] Quality checks pass

### T-010: Canonical vocab loader v0.1 (RecipeNLG + FlavorDB)
**Description:** `pantryatlas/data/build_vocab.py` is the offline pipeline that produces `ingredients.parquet` and `compounds.parquet`. **v0.1 scope is intentionally narrow**: pull RecipeNLG (English) + FlavorDB (compound table) only. Run lightweight NER on the RecipeNLG ingredient strings, dedupe by exact + fuzzy (rapidfuzz ≥ 0.92) + semantic (bge-m3 cosine ≥ 0.92), and emit a parquet with columns `canonical_name, language, aliases (list[str]), source`. `aliases` includes empty lists for non-English entries in v0.1 — multilingual aliases come in v0.2 when XiaChuFang/Povarenok/etc. land. `compounds.parquet` mirrors FlavorDB's compound table directly.

**Acceptance Criteria:**
- [ ] `python -m pantryatlas.data.build_vocab` produces `ingredients.parquet` and `compounds.parquet` under `pantryatlas/data/`
- [ ] `ingredients.parquet` has ≥1,500 unique canonical English ingredient rows
- [ ] `compounds.parquet` mirrors the FlavorDB compound table (row count + column names documented)
- [ ] Schema includes the `aliases` column as `list[str]` even though most v0.1 rows are `[]`
- [ ] Pipeline runs on Pi 5 in <2 hours (record actual time in a comment at top of artifact)
- [ ] README explicitly flags deferred sources: `# Deferred to v0.2: XiaChuFang, Povarenok, Tarladalal (IN), Cookpad (ID/VN), Recetas (ES), Yemek (TR), Chefkoch (DE)`
- [ ] Quality checks pass

### T-011: Memory-pressure monitor + systemd units
**Description:** `pantryatlas/ops/mem_monitor.py` is a small daemon that watches `psutil.virtual_memory().percent`; when it crosses 85% it sets a flag at `~/.pantryatlas/runner.blocked` that `GemmaRunner.start()` checks before launching. Ships systemd unit templates under `ops/systemd/`: `pantryatlas-gemma.service`, `pantryatlas-mem-monitor.service`, `pantryatlas-embeddings.service` (sidecar). All units use `User=pantryatlas`, `Restart=on-failure`, `LimitMEMLOCK=infinity`.

**Acceptance Criteria:**
- [ ] `pantryatlas-mem-monitor` writes the block-flag when forced to high RAM (test by mocking `psutil`)
- [ ] `GemmaRunner.start()` refuses to start (raises `MemoryPressureError`) when the block-flag exists
- [ ] All three systemd units pass `systemd-analyze verify ops/systemd/*.service`
- [ ] `ops/systemd/install.sh` copies units to `/etc/systemd/system/` and `systemctl daemon-reload`s
- [ ] Quality checks pass

### T-012: Integration smoke test on Pi
**Description:** `tests/integration/test_end_to_end_pi.py` is a single test (marked `@pytest.mark.pi_integration`) that exercises the whole stack on a real Pi: bootstrap → embed three ingredient strings → upsert into `IngredientStore` → query nearest → start Gemma → ask it to narrate the substitution → tear down. Documented as the canary test before tagging v0.1.0.

**Acceptance Criteria:**
- [ ] Test passes on a Pi 5 8GB with the full bootstrap completed
- [ ] Test is opt-in (skipped by default unless `PANTRYATLAS_PI_INTEGRATION=1`)
- [ ] Total runtime <3 min on the target hardware
- [ ] If Gemma narration step fails validation, the test fails with a clear message naming which step
- [ ] Quality checks pass

### T-013: Documentation
**Description:** Write `README.md` (project overview, quickstart, link to suite), `docs/install-pi5.md` (the "$80 Pi" community-kitchen guide), `docs/api.md` (every public symbol with a one-line description and one example), `docs/deferred-v0.2.md` (ICA+GMM, full multilingual vocab pipeline, FastAPI auth, additional corpora). Each doc page front-matter includes "last updated" date and "verified against commit" SHA placeholder.

**Acceptance Criteria:**
- [ ] All four docs exist and are linked from `README.md`
- [ ] `docs/install-pi5.md` is followable by someone with shell experience but no Python background (one-screen-per-step, no jargon without expansion)
- [ ] `docs/api.md` covers every symbol exported from `pantryatlas/__init__.py`
- [ ] `docs/deferred-v0.2.md` enumerates the 5 deferred items (mode discovery, vocab pipeline expansion, audio/photo, federation, USDA layer) with a one-paragraph rationale each
- [ ] Quality checks pass

### T-014: v0.1.0 release
**Description:** Final release prep: bump `pyproject.toml` version to `0.1.0`, write CHANGELOG entry covering tasks T-001..T-013, tag `v0.1.0`, push tag. Open a tracking issue in the org for v0.2 scope listing the deferred items.

**Acceptance Criteria:**
- [ ] `pyproject.toml` version = `0.1.0`
- [ ] `CHANGELOG.md` has a `## [0.1.0] - YYYY-MM-DD` section
- [ ] `git tag v0.1.0` exists and is pushed
- [ ] `pantryatlas/pantryatlas#1` issue exists titled "v0.2 scope tracker" listing deferred items
- [ ] CI green on the tagged commit
- [ ] Quality checks pass

## 4. Functional Requirements

- **FR-1:** The package must install on a Pi 5 8GB running Raspberry Pi OS Bookworm via a single bootstrap script in <30 min.
- **FR-2:** `pantryatlas.embed(texts)` must return a `(len(texts), 1024)` float32 ndarray with unit-norm rows for any list of multilingual text strings.
- **FR-3:** The Gemma 4 runner must auto-select the E4B model when ≥6 GiB of RAM is free, otherwise the E2B model.
- **FR-4:** The Gemma 4 client must default to a relaxed-JSON + repair-loop pattern for structured output; strict grammar-constrained output must be opt-in.
- **FR-5:** `IngredientStore`, `RecipeStore`, and `ModeStore` must persist across process restart via sqlite-vec.
- **FR-6:** `slerp(a, b, t)` must match a reference NumPy implementation to within 1e-6 for unit-norm inputs, including the `dot ≈ 1` short-circuit case.
- **FR-7:** `constrained_slerp(a, b, t, mode_basis)` must produce a result whose projection onto `mode_basis` is ≥ that of `a`.
- **FR-8:** `Pantry.resolve(raw_text)` must apply exact → fuzzy → semantic matching in that order and return either a canonical `Ingredient` or `None`.
- **FR-9:** The vocab loader must emit `ingredients.parquet` with a `list[str]` `aliases` column even when most rows have `[]` (forward-compatible with v0.2 multilingual expansion).
- **FR-10:** The memory-pressure monitor must prevent the Gemma runner from starting when RAM pressure exceeds 85%.
- **FR-11:** All public symbols exported from `pantryatlas/__init__.py` must appear in `docs/api.md` with an example.
- **FR-12:** All Gemma 4 spec claims used in design decisions must be either verified-with-source or marked unverified in `docs/gemma4-verified-specs.md`.

## 5. Non-Goals (Out of Scope for v0.1.0)

- **No user-facing application code.** This package is library + ops only. Apps live in repos 2–5.
- **No ICA + GMM mode-discovery pipeline.** `ModeStore` ships with the schema reserved but no insert path; the unsupervised mode-discovery work moves to v0.2 / `mode-atlas`.
- **No XiaChuFang, Povarenok, Tarladalal, Cookpad, Recetas, Yemek, or Chefkoch corpora ingestion.** v0.1 vocab is RecipeNLG (English) + FlavorDB only.
- **No multilingual alias population in v0.1.** The `aliases` column exists and is empty for most rows; cross-language aliases come in v0.2.
- **No strict-JSON / grammar-constrained Gemma output as the default path.** It's opt-in; docs warn about the latency cost.
- **No REST/HTTP API at the suite level.** Only the optional embedding sidecar (and llama.cpp's own server) bind ports.
- **No authentication, no Tailscale config, no Cloudflare tunnel.** Those belong to deployment / `pantryatlas-mcp`.
- **No photo or audio ingestion.** Gemma 4 vision/audio modalities are deferred regardless of whether T-001 confirms they exist.
- **No nutritional layer (USDA FoodData Central).** Deferred.
- **No federation across multiple Pis.** Deferred.

## 6. Technical Considerations

- **Pi 5 8GB RAM budget:** Gemma 4 E4B Q4_K_M (~3 GB) + bge-m3 int8 ONNX (~600 MB) + sqlite-vec corpus (<500 MB) + Python/FastAPI/OS (~1 GB) ≈ 5.1 GB used, leaving ~2.9 GB for downstream apps. E2B fallback (~1.5 GB) recovers another 1.5 GB when needed.
- **llama.cpp build flags:** ARM64-tuned; Gemma 4 hybrid-attention flag set must be confirmed in T-001 before T-003 pins them.
- **Structured-JSON latency (per `local-llm-ops` T9):** `json_schema strict:true` on Pi CPU was measured at ~6 min/batch. The relaxed + repair path in T-005 is the design response; strict mode is preserved but opt-in only.
- **Multilingual coverage in v0.1:** Comes from bge-m3 at the embedding layer, not from the vocab. A Spanish ingredient string will embed near its English canonical equivalent even without an alias entry. v0.2 will add explicit aliases.
- **sqlite-vec choice:** Zero-daemon, single-file, survives Pi power loss cleanly. Validated for the use case in the cross-cutting-decisions section of the prose plan.
- **License:** Apache 2.0 throughout to match Gemma 4 and signal NGO/government compatibility.

## 7. Success Metrics

- A fresh Pi 5 8GB reaches a working `pantryatlas` install in <30 min following only `docs/install-pi5.md`.
- The integration smoke test (T-012) passes end-to-end in <3 min on the target hardware.
- `embed()` throughput ≥17 ingredient strings/sec on Pi 5 (i.e. 1,000 strings in <60s).
- Gemma 4 E4B `generate()` returns 256 tokens in <30s on Pi 5.
- Total `pantryatlas` install + model footprint ≤6 GB on disk, ≤5.5 GB resident at runtime.
- Downstream repos (`pantry-navigator`, etc.) can import and use every primitive listed in FR-1 through FR-10 without reimplementing it.

## 8. Open Questions

- **OQ-1:** Does Gemma 4 actually expose a native system-prompt role, or is it the same chat-template trick as Gemma 3? Resolved in T-001.
- **OQ-2:** Is the 256K context claim a property of the architecture or only enabled with specific GGUF builds / runtime flags? Resolved in T-001.
- **OQ-3:** Which exact RecipeNLG license terms apply to redistributing the derived `ingredients.parquet`? T-010 must check before shipping the artifact in the package.
- **OQ-4:** Should the bge-m3 ONNX file ship inside the package or be downloaded by `pi-bootstrap.sh`? Default position: download in bootstrap (keep wheel small), but revisit if it breaks offline-install scenarios.
- **OQ-5:** Self-hosted ARM64 GitHub Actions runner vs. emulated `linux/arm64` in `qemu` for CI — T-002 makes a call and documents it.
- **OQ-6:** Where do we draw the line on `Quantity` parsing? v0.1 minimum is "store the raw string"; the question is whether to attempt unit normalization at all. Default position: defer to `pantry-navigator`.
