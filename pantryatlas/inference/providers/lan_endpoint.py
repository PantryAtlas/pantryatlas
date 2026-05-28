"""LAN endpoint provider: an OpenAI-compatible LLM elsewhere on the network."""
from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from pantryatlas.gemma.client import GemmaClient
from pantryatlas.inference.config import ProviderConfig
from pantryatlas.inference.provider import (
    Capability,
    CapabilityUnavailable,
    ProviderInfo,
)

_HEALTH_TTL_S = 10.0


class LanEndpointProvider:
    kind: str = "lan"

    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        priority: int,
        capabilities: list[Capability],
        enabled: bool = True,
        client: GemmaClient | None = None,
        health_check: Callable[[], bool] | None = None,
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.priority = priority
        self.capabilities = set(capabilities)
        self.enabled = enabled
        self._client = client or GemmaClient(base_url=self.base_url)
        self._health_check = health_check or self._default_probe
        self._cache: tuple[float, bool] | None = None

    def _default_probe(self) -> bool:
        try:
            r = httpx.get(f"{self.base_url}/health", timeout=2.0)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def is_available(self) -> bool:
        if not self.enabled:
            return False
        now = time.monotonic()
        if self._cache and now - self._cache[0] < _HEALTH_TTL_S:
            return self._cache[1]
        ok = self._health_check()
        self._cache = (now, ok)
        return ok

    def force_probe(self) -> bool:
        self._cache = None
        return self.is_available()

    def generate(self, system: str, user: str, **kwargs) -> str | dict:
        return self._client.generate(system=system, user=user, **kwargs)

    def vision_generate(self, image_bytes: bytes, prompt: str, system: str) -> str:
        if "vision" not in self.capabilities:
            raise CapabilityUnavailable("vision")
        return self._client.vision_generate(
            image_bytes=image_bytes, prompt=prompt, system=system
        )

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name=self.name, kind="lan", capabilities=sorted(self.capabilities),
            priority=self.priority, enabled=self.enabled, available=self.is_available(),
        )

    def to_config(self) -> ProviderConfig:
        return ProviderConfig(
            name=self.name, kind="lan", priority=self.priority, enabled=self.enabled,
            capabilities=sorted(self.capabilities), base_url=self.base_url,
        )
