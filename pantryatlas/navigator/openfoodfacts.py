"""Open Food Facts lookup client (pure HTTP, no caching).

OFF is a free, keyless public product database. This client does ONE thing:
GET a product by barcode. Caching lives in KitchenStore; routing decides
cache-first. ``transport`` is injectable for httpx.MockTransport tests.
"""

from __future__ import annotations

import httpx

_DEFAULT_BASE_URL = "https://world.openfoodfacts.org"
# OFF asks API users to send a descriptive UA; a generic Python UA is also
# bot-blocked by some CDNs (see project memory). Identify ourselves.
_USER_AGENT = "PantryAtlas/0.2 (+https://pantryatlas.org)"
_FIELDS = "product_name,brands,categories_tags,ingredients_tags"


class OffUnavailable(Exception):
    """Raised when OFF cannot be reached / returns a server error."""


class OpenFoodFactsClient:
    def __init__(self, base_url: str = _DEFAULT_BASE_URL, timeout_s: float = 6.0,
                 transport: httpx.BaseTransport | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            timeout=timeout_s,
            headers={"User-Agent": _USER_AGENT},
            transport=transport,
        )

    def get_product(self, code: str) -> dict | None:
        """Return the OFF product dict for a barcode, or None if not found.

        Raises OffUnavailable on network error / timeout / 5xx.
        """
        url = f"{self._base_url}/api/v2/product/{code}.json?fields={_FIELDS}"
        try:
            r = self._client.get(url)
        except httpx.HTTPError as exc:
            raise OffUnavailable(str(exc)) from exc
        if r.status_code == 404:
            return None
        if r.status_code >= 500:
            raise OffUnavailable(f"OFF returned {r.status_code}")
        if r.status_code != 200:
            raise OffUnavailable(f"OFF returned {r.status_code}")
        try:
            body = r.json()
        except ValueError as exc:
            raise OffUnavailable(f"OFF returned non-JSON body: {exc}") from exc
        if not isinstance(body, dict):
            raise OffUnavailable("OFF returned unexpected body shape")
        if body.get("status") != 1:
            return None
        return body.get("product")

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> OpenFoodFactsClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
