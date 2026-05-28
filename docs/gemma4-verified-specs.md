---
last_updated: 2026-05-28
verified_by: claude-sonnet-4-6
chosen_gguf_url: https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF/resolve/main/gemma-4-E4B-it-Q4_K_M.gguf
chosen_gguf_sha256: 519b9793ed6ce0ff530f1b7c96e848e08e49e7af4d57bb97f76215963a54146d
chosen_gguf_size_gb: 4.98
chosen_gguf_quantization: Q4_K_M
mmproj_url: https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF/resolve/main/mmproj-F16.gguf
mmproj_sha256: ddf46c21d7078e95338cfc22306b19b276a29a5ad089023449dd54d4b6170a51
mmproj_size_gb: 0.99
context_length_max_tokens: 131072
ground_truth_sources:
  - google_primary
  - local_llm_ops_install
---

# Gemma 4 Verified Specs

**Model under review:** Gemma 4 E4B (Effective 4B) — the variant that fits on a 15 GB Pi 5 at Q4_K_M quantization.
**Operator context:** `~/local-llm-ops/` uses `gemma4-4b` via the Ollama registry (a separate deployment path from the direct GGUF used here). Both refer to the same base model: Google's `google/gemma-4-E4B-it` released 2026-04-02.

---

## Claim Verification Table

Each block has a `verified` field set to `true` (primary source confirms the asserted value) or `false` (asserted value does not match what sources show, with fallback action).

---

### context_length

```yaml
context_length:
  asserted_by_project_prose: 256K
  actual_for_E4B: 128K
  verified: false
  verified_actual: true
  source: https://ai.google.dev/gemma/docs/core/model_card_4
  notes: >
    256K context exists on the 26B A4B and 31B Dense variants only.
    E4B (the only variant that fits on a 15 GB Pi 5 at Q4) is capped at 128K.
    This is a hard constraint — 26B/31B would require ~16-24 GB VRAM/RAM for Q4.
  fallback: >
    Cap all context window assumptions in T-010/T-011/T-012 to 128K max.
    If 256K is required, the project must switch to a non-Pi host or accept
    that this model cannot fulfill the spec.
```

---

### supported_languages

```yaml
supported_languages:
  asserted_by_project_prose: "140+"
  verified: true
  source: https://ai.google.dev/gemma/docs/core/model_card_4
  notes: >
    Model card states "multilingual support in over 140 languages." DeepMind landing
    page (https://deepmind.google/models/gemma/gemma-4/) confirms "Support for 140 languages."
    The asserted "140+" matches primary sources exactly.
```

---

### e4b_vision

```yaml
e4b_vision:
  asserted_by_project_prose: true
  verified: true
  source: https://ai.google.dev/gemma/docs/core/model_card_4
  notes: >
    Model card confirms all four Gemma 4 variants (E2B, E4B, 26B A4B, 31B Dense)
    support image input with variable aspect ratio and resolution. Capabilities
    include object detection, document/PDF parsing, OCR, chart comprehension,
    screen and UI understanding. Vision is not restricted to any size tier.
    Ollama tags confirm: gemma4:e4b accepts "Text, Image input."
```

---

### audio_modalities

```yaml
audio_modalities:
  asserted_by_project_prose: "E2B/E4B"
  verified: true
  source: https://ai.google.dev/gemma/docs/core/model_card_4
  notes: >
    Model card explicitly limits audio to E2B and E4B only: "Native audio capabilities
    including Automatic Speech Recognition (ASR) and speech-to-translated-text translation"
    are listed for E2B and E4B. The 26B A4B and 31B Dense models do not have
    audio support. The asserted scope ("E2B/E4B") matches primary sources.
    Google's blog post (https://blog.google/innovation-and-ai/technology/developers-tools/gemma-4/)
    confirms "native audio understanding" as a Gemma 4 capability.
```

---

### native_system_prompt

```yaml
native_system_prompt:
  asserted_by_project_prose: true
  verified: true
  source: https://huggingface.co/google/gemma-4-31B-it/blob/main/README.md
  source_2: https://ai.google.dev/gemma/docs/core/prompt-formatting-gemma4
  notes: >
    Gemma 4 introduces native support for the `system` role. The official HuggingFace
    README for google/gemma-4-31B-it states: "Native System Prompt Support — Gemma 4
    introduces native support for the system role, enabling more structured and
    controllable conversations. Compared to Gemma 3, the models use standard system,
    assistant, and user roles."

    The Gemma 4 prompt-formatting doc (prompt-formatting-gemma4) shows the token
    format: <|turn>system ... <turn|>. Chat libraries (Transformers, llama.cpp)
    handle the template automatically.

    IMPORTANT disambiguation: An older page at /gemma/docs/core/prompt-structure
    states "the system role is not supported" — this applies to Gemma 3 and below.
    The Gemma 4-specific page at /gemma/docs/core/prompt-formatting-gemma4 supersedes
    it for Gemma 4 models.

    Since native_system_prompt is verified TRUE, T-010/T-011/T-012 do NOT need
    a role-prefix shim. Standard {"role": "system", "content": "..."} messages work.
```

---

## Chosen GGUF Details

```
chosen_gguf_url:     https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF/resolve/main/gemma-4-E4B-it-Q4_K_M.gguf
chosen_gguf_sha256:  519b9793ed6ce0ff530f1b7c96e848e08e49e7af4d57bb97f76215963a54146d
chosen_gguf_size_gb: 4.98
chosen_gguf_quantization: Q4_K_M
```

**Source:** `unsloth/gemma-4-E4B-it-GGUF` on HuggingFace (https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF).
The SHA256 is the file-content hash displayed on the HuggingFace blob page under "Xet Pointer Details" — this is the same hash `sha256sum` produces on the downloaded file.

**Verify on bootstrap (T-009 must do this):**
```bash
sha256sum gemma-4-E4B-it-Q4_K_M.gguf
# Expected: 519b9793ed6ce0ff530f1b7c96e848e08e49e7af4d57bb97f76215963a54146d
```

**Alternative authoritative source:** `ggml-org/gemma-4-E4B-it-GGUF` (the llama.cpp team's canonical quants, https://huggingface.co/ggml-org/gemma-4-E4B-it-GGUF). Their Q4_K_M is 5.34 GB (different byte count from unsloth's 4.98 GB — different quantizer version). If unsloth's URL becomes unavailable, use ggml-org and re-verify the hash.

**Ollama disambiguation:** The operator's `~/local-llm-ops/` install uses `ollama pull gemma4-4b` → Ollama resolves this to `gemma4:e4b-it-q4_K_M` (9.6 GB with Ollama wrapper metadata). T-009 uses the bare GGUF via llama.cpp, not Ollama, so these hashes will not match — that is expected.

---

## T-014: Vision Approach — Gemma 4 E4B Multimodal via llama.cpp

### Approach

Gemma 4 E4B is natively multimodal (verified in `e4b_vision` block above). The vision endpoint
(`POST /navigator/vision/parse-shelf`) uses the existing `GemmaClient.vision_generate()` method,
which posts an OpenAI-compatible chat-completions payload with the image encoded as a base64
`image_url` content block:

```json
{
  "role": "user",
  "content": [
    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,<...>"}},
    {"type": "text", "text": "What ingredients do you see on this shelf? ..."}
  ]
}
```

This is the multimodal message format llama-server accepts when started with `--mmproj`.

### mmproj Requirement

llama-server requires a vision projector GGUF (`--mmproj`) in addition to the base model GGUF
to process image inputs. Without `--mmproj`, the server returns 400/422 on vision requests, which
`GemmaClient.vision_generate()` catches and raises as `VisionUnavailable` → HTTP 503.

**Pinned mmproj (verified 2026-05-28 against HuggingFace LFS metadata):**
`unsloth/gemma-4-E4B-it-GGUF` ships three vision projectors. We pin **F16** — it
matches the text-model precision needs at ~half the size of F32 and is the
Pi-CPU choice.

```
mmproj_url:    https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF/resolve/main/mmproj-F16.gguf
mmproj_sha256: ddf46c21d7078e95338cfc22306b19b276a29a5ad089023449dd54d4b6170a51
mmproj_size_gb: 0.99
```

Alternatives in the same repo (use only if F16 is unavailable; re-pin the SHA):

| file | size | sha256 |
|---|---|---|
| `mmproj-F16.gguf` (pinned) | 0.99 GB | `ddf46c21d7078e95338cfc22306b19b276a29a5ad089023449dd54d4b6170a51` |
| `mmproj-BF16.gguf` | 0.99 GB | `ee01cba03fd9c71ea2ea722225d24a84f72e7197714367e550ef705ef8851bc6` |
| `mmproj-F32.gguf` | 1.91 GB | `343cdea7775835ebdd1caa6c42ec3ec3e711d082835c72253d4e87c4b7e303d0` |

`ops/pi-bootstrap.sh` downloads `mmproj-F16.gguf` into `~/pantryatlas/models/` and
verifies this SHA alongside the main GGUF (`stage_gemma_download`).

### Enabling vision (wired 2026-05-28)

`GemmaRunner(vision=True)` appends `--mmproj <models_dir>/mmproj-F16.gguf` to the
llama-server command (see `runner.py` `_build_command`); it raises
`FileNotFoundError` if the mmproj isn't present. The navigator server constructs
a vision `GemmaClient` only when **`PANTRYATLAS_VISION=1`** is set (see
`_build_vision_client`); otherwise `/navigator/vision/parse-shelf` returns 503.

End-to-end enable on a bootstrapped Pi:

```bash
# 1. Bootstrap downloads the model + mmproj-F16.gguf (verified)
bash ops/pi-bootstrap.sh

# 2. Run llama-server WITH the projector (port 8080)
llama-server \
  -m ~/pantryatlas/models/gemma-4-E4B-it-Q4_K_M.gguf \
  --mmproj ~/pantryatlas/models/mmproj-F16.gguf \
  --host 127.0.0.1 --port 8080 -c 8192 --threads 3

# 3. Start the navigator with vision enabled
PANTRYATLAS_VISION=1 uvicorn pantryatlas.navigator.server:app --host 0.0.0.0 --port 8090
```

### Measured Pi Latency

**Status: NOT YET MEASURED on hardware.** Code path is wired (runner `--mmproj`,
env-gated vision client, bootstrap download, SHA pinned) but a live run requires
a bootstrapped Gemma stack (llama.cpp built + the ~5 GB model + the ~1 GB mmproj)
and a real shelf photo — the repo fixture (`tests/fixtures/test-shelf.jpg`) is a
synthetic 4-blob image suitable only for the mock unit tests.

Expected range: 15–60 s per image on Pi 5 (8 GB) at Q4_K_M based on text-only TPS
(~1–3 TPS for E4B) plus vision-projection overhead. Update this after the first
live run. The endpoint is on the **navigator** server (port 8090), which calls
the gemma llama-server (8080) internally:

```bash
time curl -F image=@/path/to/real-shelf.jpg http://127.0.0.1:8090/navigator/vision/parse-shelf
```

### Graceful Fallback

When the mmproj is not loaded, the endpoint returns HTTP 503 `{"error":"vision_unavailable"}`.
The frontend (`PhotoReviewSheet.tsx`) already handles 503 gracefully by showing
"Photo recognition isn't set up on this server yet — type ingredients for now."
This is the **production default** until the operator downloads and wires the mmproj.

### Response Contract

The endpoint returns both a structured form and a flat list to satisfy both consumers:

```json
{
  "detected": [{"label": "tomato", "confidence": 0.92}, ...],
  "items":    ["tomato", ...]
}
```

`PhotoReviewSheet.tsx` reads `data.items` (flat list); other consumers can use `data.detected`
for confidence-aware filtering.

---

## Downstream Impact Summary

| Claim | Asserted | Verified | Action Required |
|---|---|---|---|
| context_length | 256K | FALSE — E4B is 128K | T-010/T-011/T-012: cap at 128K |
| supported_languages | 140+ | TRUE | No change needed |
| e4b_vision | true | TRUE | No change needed |
| audio_modalities | E2B/E4B | TRUE | No change needed |
| native_system_prompt | true | TRUE | No role-prefix shim needed in T-010/T-011/T-012 |

The only actionable mismatch is **context_length**. All other claims are confirmed by primary Google sources.

---

## Primary Sources Used

- Google AI for Developers — Gemma 4 model card: https://ai.google.dev/gemma/docs/core/model_card_4
- Google AI for Developers — Gemma 4 prompt formatting: https://ai.google.dev/gemma/docs/core/prompt-formatting-gemma4
- Google AI for Developers — Gemma 4 releases: https://ai.google.dev/gemma/docs/releases
- Google DeepMind — Gemma 4 landing page: https://deepmind.google/models/gemma/gemma-4/
- Google Blog — Gemma 4 announcement: https://blog.google/innovation-and-ai/technology/developers-tools/gemma-4/
- HuggingFace — google/gemma-4-31B-it README: https://huggingface.co/google/gemma-4-31B-it/blob/main/README.md
- HuggingFace — unsloth/gemma-4-E4B-it-GGUF (GGUF + SHA256): https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF/blob/main/gemma-4-E4B-it-Q4_K_M.gguf
- Ollama — gemma4 library: https://ollama.com/library/gemma4
