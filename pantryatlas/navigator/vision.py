"""T-014: Shelf-photo ingredient detection via Gemma 4 E4B multimodal.

Public API
----------
parse_shelf(image_bytes, gemma_client) -> list[DetectedIngredient]
    Preprocess a shelf photo, call the client's vision method, and parse
    the structured JSON response.

VisionUnavailable
    Raised when the vision model/mmproj is not loaded or reachable.
    The route handler catches this and returns HTTP 503.
"""

from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pantryatlas.gemma.client import GemmaClient

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class VisionUnavailable(RuntimeError):
    """Raised when the llama-server vision model/mmproj is not loaded.

    The navigator route catches this exception and returns HTTP 503
    ``{"error":"vision_unavailable"}``, which the frontend treats as
    graceful degradation (shows "type ingredients for now" message).
    """


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

_MAX_SIDE_PX = 896  # Resize longest side to this before sending to model
_JPEG_QUALITY = 85

_SYSTEM_PROMPT = (
    "You are a kitchen inventory assistant. "
    "You will receive an image of a pantry or refrigerator shelf. "
    "Identify every food ingredient you can see. "
    "Return ONLY a JSON object with this exact structure — no prose, no markdown:\n"
    '{"detected":[{"label":"<ingredient name>","confidence":<0.0–1.0>}]}\n'
    "Use lowercase English ingredient names. "
    "If you see nothing, return {\"detected\":[]}."
)

_USER_PROMPT = "What ingredients do you see on this shelf? Return the JSON object."


@dataclass
class DetectedIngredient:
    """A single ingredient detected from a shelf photo."""

    label: str
    confidence: float


# ---------------------------------------------------------------------------
# Image preprocessing
# ---------------------------------------------------------------------------


def _preprocess(image_bytes: bytes) -> bytes:
    """Resize (preserving aspect ratio) and EXIF-rotate a shelf photo.

    Returns JPEG bytes suitable for embedding in the model request.
    Requires Pillow (PIL); already installed as a transitive dep on Pi.
    """
    from PIL import Image, ImageOps  # imported lazily to avoid mandatory dep at module level

    with Image.open(io.BytesIO(image_bytes)) as img:
        # Auto-rotate based on EXIF orientation tag
        img = ImageOps.exif_transpose(img)

        # Convert palette or RGBA to RGB so JPEG can be saved
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        # Resize so the longest side is ≤ _MAX_SIDE_PX (bicubic, preserves ratio)
        w, h = img.size
        scale = min(_MAX_SIDE_PX / max(w, h), 1.0)
        if scale < 1.0:
            new_w = max(1, int(w * scale))
            new_h = max(1, int(h * scale))
            img = img.resize((new_w, new_h), Image.BICUBIC)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_JPEG_QUALITY)
        return buf.getvalue()


# ---------------------------------------------------------------------------
# Response parsing with repair fallback
# ---------------------------------------------------------------------------


def _parse_detected(text: str) -> list[DetectedIngredient] | None:
    """Try to extract and parse the detected-ingredients JSON from model output.

    Returns None if parsing fails completely.
    """
    # Direct parse first
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "detected" in obj:
            return _coerce_list(obj["detected"])
    except json.JSONDecodeError:
        pass

    # Try to extract first {...} block (model may wrap in prose)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            obj = json.loads(match.group(0))
            if isinstance(obj, dict) and "detected" in obj:
                return _coerce_list(obj["detected"])
        except json.JSONDecodeError:
            pass

    # Regex rescue: extract label strings from partial JSON
    labels = re.findall(r'"label"\s*:\s*"([^"]+)"', text)
    if labels:
        return [DetectedIngredient(label=lbl.strip().lower(), confidence=0.5) for lbl in labels]

    return None


def _coerce_list(raw: object) -> list[DetectedIngredient]:
    """Coerce the raw ``detected`` value to a list of DetectedIngredient."""
    if not isinstance(raw, list):
        return []
    result = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        if not isinstance(label, str) or not label.strip():
            continue
        try:
            confidence = float(item.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))
        result.append(DetectedIngredient(label=label.strip().lower(), confidence=confidence))
    return result


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def parse_shelf(image_bytes: bytes, gemma_client: GemmaClient) -> list[DetectedIngredient]:
    """Detect ingredients in a shelf photo.

    Preprocesses the image, calls ``gemma_client.vision_generate()``, and
    parses the structured JSON response.  Raises ``VisionUnavailable`` if
    the client reports that the vision model/mmproj is not loaded.

    Args:
        image_bytes: Raw bytes of a JPEG or PNG shelf photo.
        gemma_client: A ``GemmaClient`` instance with ``vision_generate()``.

    Returns:
        List of ``DetectedIngredient`` objects (may be empty if none detected).

    Raises:
        VisionUnavailable: If the model/mmproj is not loaded or not reachable.
    """
    processed = _preprocess(image_bytes)
    # vision_generate raises VisionUnavailable if mmproj is not loaded
    raw = gemma_client.vision_generate(
        image_bytes=processed,
        prompt=_USER_PROMPT,
        system=_SYSTEM_PROMPT,
    )

    result = _parse_detected(raw)
    if result is None:
        # Malformed response — return empty rather than crash
        return []
    return result
