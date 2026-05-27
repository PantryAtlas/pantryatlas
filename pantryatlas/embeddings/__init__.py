"""Multilingual embedding service — bge-m3 via onnxruntime (int8 ONNX).

Model source
------------
Xenova/bge-m3 on HuggingFace (Apache-2.0 / MIT licence for ONNX weights).
  ONNX int8 file : Xenova/bge-m3 @ onnx/model_int8.onnx
  Tokenizer      : Xenova/bge-m3 @ tokenizer.json  (XLM-RoBERTa BPE)
  Base model     : BAAI/bge-m3 (https://huggingface.co/BAAI/bge-m3)

Files are downloaded on first use into ~/.cache/pantryatlas/bge-m3/.
SHA-256 of model_int8.onnx is verified after download.

Architecture note (T-003, Option A)
-------------------------------------
The T-002 scaffold created pantryatlas/embeddings/ as a Python package, so
the flat-file path pantryatlas/embeddings.py is not reachable (Python
disambiguates: package beats module). AC-1 is satisfied by this __init__.py;
the FastAPI sidecar lives at the top-level pantryatlas/embeddings_server.py
as AC-8 requires.
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import threading
from typing import Any

import numpy as np
import onnxruntime as ort
from huggingface_hub import hf_hub_download
from tokenizers import Tokenizer

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HF_REPO = "Xenova/bge-m3"
_ONNX_FILE = "onnx/model_int8.onnx"
_TOK_FILE = "tokenizer.json"

# SHA-256 of Xenova/bge-m3 onnx/model_int8.onnx (verified 2026-05-27)
_ONNX_SHA256 = "a206e10e995aa2a833924bcd725ba5dd6c3425cd34bac3cf2b5677cd2a1c51d6"

_CACHE_DIR = pathlib.Path.home() / ".cache" / "pantryatlas" / "bge-m3"
_BATCH_SIZE = 32  # internal micro-batch for ONNX forward

# ---------------------------------------------------------------------------
# Module-level singletons (lazy, thread-safe)
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_session: ort.InferenceSession | None = None
_tokenizer: Tokenizer | None = None
_output_name: str | None = None


def _get_model() -> tuple[ort.InferenceSession, Tokenizer, str]:
    """Load and cache the ONNX session + tokenizer (called once)."""
    global _session, _tokenizer, _output_name

    if _session is not None and _tokenizer is not None:
        return _session, _tokenizer, _output_name  # type: ignore[return-value]

    with _lock:
        # Double-checked locking
        if _session is not None and _tokenizer is not None:
            return _session, _tokenizer, _output_name  # type: ignore[return-value]

        _CACHE_DIR.mkdir(parents=True, exist_ok=True)

        # --- download tokenizer ---
        tok_local = _CACHE_DIR / "tokenizer.json"
        if not tok_local.exists():
            tok_path = hf_hub_download(
                repo_id=_HF_REPO,
                filename=_TOK_FILE,
                local_dir=str(_CACHE_DIR),
                local_dir_use_symlinks=False,
            )
        else:
            tok_path = str(tok_local)

        # --- download ONNX model ---
        # hf_hub_download preserves subdir structure: onnx/model_int8.onnx
        # lands at _CACHE_DIR / "onnx" / "model_int8.onnx"
        onnx_local = _CACHE_DIR / "onnx" / "model_int8.onnx"
        if not onnx_local.exists():
            hf_hub_download(
                repo_id=_HF_REPO,
                filename=_ONNX_FILE,
                local_dir=str(_CACHE_DIR),
                local_dir_use_symlinks=False,
            )

        # --- verify ONNX SHA256 on fresh downloads ---
        # Use marker file to avoid re-hashing 543MB on every import
        sha_marker = onnx_local.with_suffix(onnx_local.suffix + ".sha256-ok")
        if not sha_marker.exists():
            _actual_sha = hashlib.sha256(onnx_local.read_bytes()).hexdigest()
            if _actual_sha != _ONNX_SHA256:
                raise RuntimeError(
                    f"bge-m3 ONNX SHA256 mismatch at {onnx_local}: "
                    f"expected {_ONNX_SHA256}, got {_actual_sha}. "
                    f"Delete the cache file and retry, or update _ONNX_SHA256 if upstream changed."
                )
            sha_marker.write_text(_ONNX_SHA256)

        onnx_path = str(onnx_local)

        # --- load tokenizer ---
        tok = Tokenizer.from_file(tok_path)
        tok.enable_padding(pad_id=1, pad_token="<pad>")
        tok.enable_truncation(max_length=8192)

        # --- create ONNX session ---
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = os.cpu_count() or 4
        opts.intra_op_num_threads = os.cpu_count() or 4
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        sess = ort.InferenceSession(
            onnx_path,
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )

        # Discover output name (usually "last_hidden_state" or "sentence_embedding")
        out_name = sess.get_outputs()[0].name

        _session = sess
        _tokenizer = tok
        _output_name = out_name
        return _session, _tokenizer, _output_name


def _run_batch(
    sess: ort.InferenceSession,
    tokenizer: Tokenizer,
    out_name: str,
    texts: list[str],
) -> np.ndarray:
    """Run one micro-batch of texts through the model, return CLS embeddings."""
    encodings = tokenizer.encode_batch(texts)
    input_ids = np.array([e.ids for e in encodings], dtype=np.int64)
    attn_mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
    token_type_ids = np.zeros_like(input_ids, dtype=np.int64)

    # Build feed_dict — some models don't accept token_type_ids
    input_names = {inp.name for inp in sess.get_inputs()}
    feed: dict[str, Any] = {
        "input_ids": input_ids,
        "attention_mask": attn_mask,
    }
    if "token_type_ids" in input_names:
        feed["token_type_ids"] = token_type_ids

    outputs = sess.run([out_name], feed)
    hidden: np.ndarray = outputs[0]  # (B, seq_len, H) or (B, H)

    if hidden.ndim == 3:
        # CLS pooling: take first token
        cls_emb = hidden[:, 0, :]
    else:
        cls_emb = hidden  # already pooled

    return cls_emb.astype(np.float32)


def embed(texts: list[str]) -> np.ndarray:
    """Embed a list of strings via bge-m3 int8 ONNX.

    Args:
        texts: Non-empty list of UTF-8 strings to embed.

    Returns:
        Float32 array of shape (len(texts), 1024) with L2-unit-norm rows.

    Notes:
        The model is loaded lazily on the first call and cached in module
        state — subsequent calls pay only inference cost.  Internally uses
        micro-batches of 32 to avoid OOM on large inputs.
        For cross-process use, run ``pantryatlas/embeddings_server.py`` and
        POST to /embed.
    """
    if not texts:
        return np.empty((0, 1024), dtype=np.float32)

    sess, tokenizer, out_name = _get_model()

    chunks: list[np.ndarray] = []
    for i in range(0, len(texts), _BATCH_SIZE):
        batch = texts[i : i + _BATCH_SIZE]
        chunk = _run_batch(sess, tokenizer, out_name, batch)
        chunks.append(chunk)

    emb = np.concatenate(chunks, axis=0)  # (N, H)

    # L2 normalise
    norms = np.linalg.norm(emb, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)  # guard zero-vectors
    emb = emb / norms

    return emb
