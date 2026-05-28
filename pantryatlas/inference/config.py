"""Persistence for the provider registry (~/.pantryatlas/providers.json)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pantryatlas.inference.provider import Capability, ProviderKind

DEFAULT_CONFIG_PATH = Path.home() / ".pantryatlas" / "providers.json"


@dataclass
class ProviderConfig:
    name: str
    kind: ProviderKind
    priority: int
    enabled: bool = True
    capabilities: list[Capability] = field(default_factory=lambda: ["text"])
    base_url: str | None = None  # required when kind == "lan"


def _default_configs() -> list[ProviderConfig]:
    return [ProviderConfig(name="on-board", kind="local", priority=100, capabilities=["text"])]


def load_provider_config(path: Path = DEFAULT_CONFIG_PATH) -> list[ProviderConfig]:
    if not path.exists():
        return _default_configs()
    data = json.loads(path.read_text())
    return [ProviderConfig(**item) for item in data.get("providers", [])]


def save_provider_config(
    configs: list[ProviderConfig], path: Path = DEFAULT_CONFIG_PATH
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"providers": [asdict(c) for c in configs]}
    path.write_text(json.dumps(payload, indent=2))
