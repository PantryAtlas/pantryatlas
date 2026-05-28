"""Inference provider abstraction: capability-aware routing targets."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

Capability = Literal["text", "vision"]
ProviderKind = Literal["local", "lan"]  # reserved (not implemented): "client", "npu", "hailo"


class NoProviderAvailable(RuntimeError):
    """No enabled, reachable provider has the requested capability."""

    def __init__(self, capability: Capability):
        self.capability = capability
        super().__init__(f"No available provider for capability: {capability!r}")


class CapabilityUnavailable(RuntimeError):
    """A provider was asked for a capability it does not advertise."""

    def __init__(self, capability: Capability):
        self.capability = capability
        super().__init__(f"Provider does not support capability: {capability!r}")


@dataclass
class ProviderInfo:
    """Serializable status snapshot of a provider for the settings UI."""

    name: str
    kind: ProviderKind
    capabilities: list[Capability]
    priority: int
    enabled: bool
    available: bool


@runtime_checkable
class Provider(Protocol):
    """A routable inference backend. Lower ``priority`` is tried first."""

    name: str
    kind: ProviderKind
    capabilities: set[Capability]
    priority: int
    enabled: bool

    def is_available(self) -> bool: ...
    def force_probe(self) -> bool: ...  # bypass any health cache; re-check now
    def generate(self, system: str, user: str, **kwargs) -> str | dict: ...
    def vision_generate(self, image_bytes: bytes, prompt: str, system: str) -> str: ...
    def info(self) -> ProviderInfo: ...
