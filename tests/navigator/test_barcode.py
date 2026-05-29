# tests/navigator/test_barcode.py
from __future__ import annotations

import io

import numpy as np
import zxingcpp
from PIL import Image

from pantryatlas.navigator.barcode import decode_barcode, product_to_ingredient, upc_ean_variants
from pantryatlas.pantry.models import Ingredient


def _barcode_png(value: str = "737628064502") -> bytes:
    # Encode an EAN/UPC barcode to a PNG using zxingcpp 3.0 API.
    # create_barcode() + write_barcode_to_image() is the preferred 3.0 form;
    # the result is a zxingcpp.Image (grayscale buffer) → numpy → PIL.
    bc = zxingcpp.create_barcode(value, zxingcpp.BarcodeFormat.EAN13)
    img = zxingcpp.write_barcode_to_image(bc, scale=4)
    arr = np.array(img)
    pil = Image.fromarray(arr)
    buf = io.BytesIO()
    pil.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def test_decode_reads_barcode():
    code = decode_barcode(_barcode_png("737628064502"))
    assert code is not None
    assert "737628064502" in code  # EAN-13 may add/strip a check digit prefix


def test_decode_returns_none_when_no_barcode():
    buf = io.BytesIO()
    Image.new("RGB", (200, 200), "white").save(buf, format="PNG")
    assert decode_barcode(buf.getvalue()) is None


# --- upc_ean_variants ---


def test_upc_ean_variants_12digit_adds_ean13_prefix():
    result = upc_ean_variants("737628064502")
    assert result == ["737628064502", "0737628064502"]


def test_upc_ean_variants_13digit_leading_zero_adds_upca():
    result = upc_ean_variants("0737628064502")
    assert result == ["0737628064502", "737628064502"]


def test_upc_ean_variants_13digit_no_leading_zero_unchanged():
    result = upc_ean_variants("7376280645020")
    assert result == ["7376280645020"]


def test_upc_ean_variants_non_digit_unchanged():
    result = upc_ean_variants("ABC-123")
    assert result == ["ABC-123"]


def test_upc_ean_variants_no_duplicates():
    # A 13-digit '0'-prefixed code should never duplicate
    result = upc_ean_variants("0737628064502")
    assert len(result) == len(set(result))


# --- mapping ---
_KNOWN = {"noodles": "noodles", "rice noodles": "rice_noodles", "pasta": "pasta"}


def _fake_resolver(raw: str) -> Ingredient | None:
    canonical = _KNOWN.get(raw.strip().lower())
    return Ingredient(canonical_name=canonical, raw_text=raw) if canonical else None


def test_mapping_uses_ingredient_tag_first():
    product = {
        "product_name": "Thai Kitchen Rice Noodles", "brands": "Thai Kitchen",
        "ingredients_tags": ["en:rice-noodles"], "categories_tags": ["en:pastas", "en:noodles"],
    }
    ing, matched = product_to_ingredient(product, _fake_resolver)
    assert matched is True
    assert ing.canonical_name == "rice_noodles"   # ingredient tag wins over category tag
    assert "Rice Noodles" in ing.raw_text


def test_mapping_falls_back_to_product_name_verbatim_when_unresolvable():
    product = {"product_name": "Exotic Snack 9000", "brands": "BrandX",
               "ingredients_tags": ["en:mystery"], "categories_tags": ["en:snacks"]}
    ing, matched = product_to_ingredient(product, _fake_resolver)
    assert matched is False
    assert ing.raw_text.startswith("Exotic Snack 9000")
    assert ing.canonical_name  # non-empty slug, never blank
