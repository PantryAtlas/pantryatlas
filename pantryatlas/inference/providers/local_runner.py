"""On-board local provider: wraps the llama.cpp GemmaRunner subprocess."""
from __future__ import annotations

from pantryatlas.gemma.client import GemmaClient
from pantryatlas.gemma.runner import GemmaRunner
from pantryatlas.inference.config import ProviderConfig
from pantryatlas.inference.provider import (
    Capability,
    CapabilityUnavailable,
    ProviderInfo,
)


class LocalRunnerProvider:
    kind: str = "local"

    def __init__(
        self,
        *,
        name: str = "on-board",
        priority: int = 100,
        enabled: bool = True,
        capabilities: list[Capability] | None = None,
        runner: GemmaRunner | None = None,
        client: GemmaClient | None = None,
    ):
        self.name = name
        self.priority = priority
        self.enabled = enabled
        self.capabilities = set(capabilities or ["text"])
        self._runner = runner or GemmaRunner()
        self._client = client

    def _get_client(self) -> GemmaClient:
        if self._client is None:
            self._runner.start()  # idempotent
            self._client = GemmaClient(base_url=self._runner.url)
        return self._client

    def is_available(self) -> bool:
        return self.enabled and self._runner.is_healthy()

    def force_probe(self) -> bool:
        return self.is_available()  # no cache to bust; runner health is already live

    def generate(self, system: str, user: str, **kwargs) -> str | dict:
        return self._get_client().generate(system=system, user=user, **kwargs)

    def vision_generate(self, image_bytes: bytes, prompt: str, system: str) -> str:
        if "vision" not in self.capabilities:
            raise CapabilityUnavailable("vision")
        return self._get_client().vision_generate(
            image_bytes=image_bytes, prompt=prompt, system=system
        )

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            name=self.name, kind="local", capabilities=sorted(self.capabilities),
            priority=self.priority, enabled=self.enabled, available=self.is_available(),
        )

    def to_config(self) -> ProviderConfig:
        return ProviderConfig(
            name=self.name, kind="local", priority=self.priority,
            enabled=self.enabled, capabilities=sorted(self.capabilities),
        )
