"""Provider registry: capability-aware routing with ordered fallback."""
from __future__ import annotations

import httpx

from pantryatlas.inference.provider import (
    Capability,
    NoProviderAvailable,
    Provider,
    ProviderInfo,
)
from pantryatlas.navigator.vision import VisionUnavailable


class ProviderRegistry:
    def __init__(self, providers: list[Provider] | None = None):
        self._providers: list[Provider] = list(providers or [])

    def all(self) -> list[Provider]:
        return list(self._providers)

    def get(self, name: str) -> Provider | None:
        return next((p for p in self._providers if p.name == name), None)

    def _candidates(self, capability: Capability) -> list[Provider]:
        return sorted(
            (p for p in self._providers if capability in p.capabilities and p.enabled),
            key=lambda p: p.priority,
        )

    def generate(self, system: str, user: str, **kwargs) -> str | dict:
        last_exc: Exception | None = None
        for p in self._candidates("text"):
            if not p.is_available():
                continue
            try:
                return p.generate(system=system, user=user, **kwargs)
            except httpx.HTTPError as exc:
                last_exc = exc
                continue
        raise NoProviderAvailable("text") from last_exc

    def vision_generate(self, image_bytes: bytes, prompt: str, system: str) -> str:
        last_exc: Exception | None = None
        for p in self._candidates("vision"):
            if not p.is_available():
                continue
            try:
                return p.vision_generate(
                    image_bytes=image_bytes, prompt=prompt, system=system
                )
            except (VisionUnavailable, httpx.HTTPError) as exc:
                last_exc = exc
                continue
        raise VisionUnavailable(
            "No vision-capable provider is available"
        ) from last_exc

    def providers_status(self) -> list[ProviderInfo]:
        return [p.info() for p in sorted(self._providers, key=lambda p: p.priority)]

    def add(self, provider: Provider) -> None:
        if self.get(provider.name) is not None:
            raise ValueError(f"Provider already exists: {provider.name!r}")
        self._providers.append(provider)

    def remove(self, name: str) -> bool:
        before = len(self._providers)
        self._providers = [p for p in self._providers if p.name != name]
        return len(self._providers) != before

    def reorder(self, ordered_names: list[str]) -> None:
        """Assign priorities by position: first name => priority 10, then 20, ..."""
        for index, name in enumerate(ordered_names):
            p = self.get(name)
            if p is not None:
                p.priority = (index + 1) * 10
