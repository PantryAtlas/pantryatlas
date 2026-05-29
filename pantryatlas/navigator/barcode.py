"""Host-side barcode decode + OFF-product → canonical-ingredient mapping."""

from __future__ import annotations

import io
import re
from collections.abc import Callable

from pantryatlas.pantry.models import Ingredient


def upc_ean_variants(code: str) -> list[str]:
    """Return the barcode plus its UPC-A<->EAN-13 variant(s), decoded-form first, deduped.

    A UPC-A (12 digits) is the same product as the EAN-13 formed by prefixing '0';
    an EAN-13 beginning '0' is the same product as its 12-digit UPC-A (drop the '0').
    Non-numeric or other-length codes return just [code].
    """
    variants = [code]
    if code.isdigit():
        if len(code) == 12:
            variants.append("0" + code)
        elif len(code) == 13 and code.startswith("0"):
            variants.append(code[1:])
    # dedupe, preserve order
    seen, out = set(), []
    for v in variants:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def decode_barcode(image_bytes: bytes) -> str | None:
    """Decode the first barcode in an image, or None. Host-side (zxing-cpp)."""
    import zxingcpp
    from PIL import Image, ImageOps

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            results = zxingcpp.read_barcodes(img)
    except Exception:
        return None
    for r in results:
        text = getattr(r, "text", None)
        if text:
            return text
    return None


def _tag_to_text(tag: str) -> str:
    # "en:rice-noodles" -> "rice noodles"; "en:Rice Noodles" -> "rice noodles"
    body = tag.split(":", 1)[-1]
    return body.replace("-", " ").strip().lower()


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return s or "unknown-product"


def product_to_ingredient(
    product: dict, resolver: Callable[[str], Ingredient | None]
) -> tuple[Ingredient, bool]:
    """Map an OFF product to a canonical pantry Ingredient.

    Tries ingredients_tags (most specific) then categories_tags then the product
    name through the resolver; falls back to a verbatim product-name Ingredient.
    Returns (ingredient, matched) where matched = the resolver succeeded.
    """
    name = (product.get("product_name") or "").strip()
    brand = (product.get("brands") or "").strip()
    raw_text = f"{name} ({brand})" if name and brand else (name or brand or "scanned item")

    # ingredients_tags first (most specific), then categories (most-specific last → reversed)
    candidates: list[str] = []
    candidates += [_tag_to_text(t) for t in (product.get("ingredients_tags") or [])]
    candidates += [_tag_to_text(t) for t in reversed(product.get("categories_tags") or [])]
    if name:
        candidates.append(name.lower())

    for cand in candidates:
        if not cand:
            continue
        resolved = resolver(cand)
        if resolved is not None:
            return (
                Ingredient(canonical_name=resolved.canonical_name, raw_text=raw_text),
                True,
            )

    # Final fallback: store verbatim (user can fix on the confirm sheet)
    return (Ingredient(canonical_name=_slug(name or raw_text), raw_text=raw_text), False)
