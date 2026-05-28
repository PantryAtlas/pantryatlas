# Inference Provider Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a LAN-federated inference provider registry so PantryAtlas can route LLM/vision work to the best available device on the local network, with graceful fallback to an on-board model.

**Architecture:** A new `pantryatlas/inference/` package defines a `Provider` protocol (on-board `local` + `lan` kinds), a `ProviderRegistry` that does capability-aware routing with an ordered fallback chain, and JSON-backed config in `~/.pantryatlas/providers.json`. The registry reuses the existing `GemmaClient` (text via `generate`, vision via `vision_generate` — already shipped in T-014) and is duck-compatible with `parse_shelf`, so the navigator vision endpoint routes through it with a minimal change. A React settings panel manages providers.

**Tech Stack:** Python 3.12, FastAPI, httpx (with `MockTransport` for tests), pytest; Vite + React + TypeScript frontend.

**Spec:** `docs/superpowers/specs/2026-05-27-inference-provider-registry-design.md`

**Supersession note:** The spec described adding an `analyze_image()` extension to `GemmaClient`. That is now obsolete — T-014 shipped `GemmaClient.vision_generate(image_bytes, prompt, system)` (raises `pantryatlas.navigator.vision.VisionUnavailable`). This plan reuses `vision_generate` and does **not** add a new client method.

**Baseline:** Branch off `feat/navigator-v0.2.0` (HEAD `8b0b5a8` or later). Run `pytest -q` once before starting to confirm a green baseline.

---

### Task 1: Provider protocol, capabilities, and errors

**Files:**
- Create: `pantryatlas/inference/__init__.py`
- Create: `pantryatlas/inference/provider.py`
- Test: `tests/inference/test_provider.py`
- Create: `tests/inference/__init__.py` (empty)

- [ ] **Step 1: Write the failing test**

```python
# tests/inference/test_provider.py
from pantryatlas.inference.provider import (
    CapabilityUnavailable,
    NoProviderAvailable,
    Provider,
    ProviderInfo,
)


class _Dummy:
    name = "dummy"
    kind = "lan"
    capabilities = {"text"}
    priority = 10
    enabled = True

    def is_available(self) -> bool:
        return True

    def force_probe(self) -> bool:
        return True

    def generate(self, system, user, **kwargs):
        return "ok"

    def vision_generate(self, image_bytes, prompt, system):
        raise CapabilityUnavailable("vision")

    def info(self):
        return ProviderInfo(
            name=self.name, kind=self.kind, capabilities=["text"],
            priority=self.priority, enabled=self.enabled, available=True,
        )


def test_dummy_satisfies_provider_protocol():
    assert isinstance(_Dummy(), Provider)


def test_errors_carry_capability():
    assert NoProviderAvailable("vision").capability == "vision"
    assert CapabilityUnavailable("text").capability == "text"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/inference/test_provider.py -v`
Expected: FAIL with `ModuleNotFoundError: pantryatlas.inference.provider`

- [ ] **Step 3: Write minimal implementation**

```python
# pantryatlas/inference/__init__.py
"""LAN-federated inference provider registry."""
```

```python
# pantryatlas/inference/provider.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/inference/test_provider.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add pantryatlas/inference/__init__.py pantryatlas/inference/provider.py tests/inference/__init__.py tests/inference/test_provider.py
git commit -m "feat(inference): Provider protocol, capabilities, and errors"
```

---

### Task 2: Provider config persistence

**Files:**
- Create: `pantryatlas/inference/config.py`
- Test: `tests/inference/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/inference/test_config.py
from pantryatlas.inference.config import (
    ProviderConfig,
    load_provider_config,
    save_provider_config,
)


def test_load_missing_returns_default_local(tmp_path):
    cfgs = load_provider_config(tmp_path / "nope.json")
    assert len(cfgs) == 1
    assert cfgs[0].kind == "local"
    assert cfgs[0].capabilities == ["text"]


def test_save_then_load_round_trips(tmp_path):
    path = tmp_path / "providers.json"
    original = [
        ProviderConfig(name="on-board", kind="local", priority=100),
        ProviderConfig(
            name="desktop", kind="lan", priority=10,
            base_url="http://192.168.1.50:8080", capabilities=["text", "vision"],
        ),
    ]
    save_provider_config(original, path)
    loaded = load_provider_config(path)
    assert loaded == original
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/inference/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: pantryatlas.inference.config`

- [ ] **Step 3: Write minimal implementation**

```python
# pantryatlas/inference/config.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/inference/test_config.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add pantryatlas/inference/config.py tests/inference/test_config.py
git commit -m "feat(inference): provider config load/save with default seeding"
```

---

### Task 3: LAN endpoint provider

**Files:**
- Create: `pantryatlas/inference/providers/__init__.py` (empty)
- Create: `pantryatlas/inference/providers/lan_endpoint.py`
- Test: `tests/inference/test_lan_endpoint.py`

**Note:** `GemmaClient(base_url=..., transport=...)` accepts an `httpx.BaseTransport` for testing (see `tests/gemma/test_client_basic.py`). The provider takes an optional `health_check` callable so availability can be tested without real network.

- [ ] **Step 1: Write the failing test**

```python
# tests/inference/test_lan_endpoint.py
import httpx

from pantryatlas.gemma.client import GemmaClient
from pantryatlas.inference.provider import CapabilityUnavailable
from pantryatlas.inference.providers.lan_endpoint import LanEndpointProvider


def _fake_chat(reply: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})
    return httpx.MockTransport(handler)


def test_generate_delegates_to_client():
    client = GemmaClient(base_url="http://peer:8080", transport=_fake_chat("cumin"))
    p = LanEndpointProvider(
        name="peer", base_url="http://peer:8080", priority=10,
        capabilities=["text"], client=client, health_check=lambda: True,
    )
    assert p.generate(system="s", user="u") == "cumin"


def test_vision_without_capability_raises():
    p = LanEndpointProvider(
        name="peer", base_url="http://peer:8080", priority=10,
        capabilities=["text"], client=GemmaClient(transport=_fake_chat("x")),
        health_check=lambda: True,
    )
    try:
        p.vision_generate(b"jpegbytes", "prompt", "system")
        assert False, "expected CapabilityUnavailable"
    except CapabilityUnavailable as e:
        assert e.capability == "vision"


def test_is_available_reflects_health_and_enabled():
    p = LanEndpointProvider(
        name="peer", base_url="http://peer:8080", priority=10,
        capabilities=["text"], client=GemmaClient(transport=_fake_chat("x")),
        health_check=lambda: True,
    )
    assert p.is_available() is True
    p.enabled = False
    assert p.is_available() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/inference/test_lan_endpoint.py -v`
Expected: FAIL with `ModuleNotFoundError: pantryatlas.inference.providers.lan_endpoint`

- [ ] **Step 3: Write minimal implementation**

```python
# pantryatlas/inference/providers/__init__.py
"""Concrete inference providers."""
```

```python
# pantryatlas/inference/providers/lan_endpoint.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/inference/test_lan_endpoint.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add pantryatlas/inference/providers/__init__.py pantryatlas/inference/providers/lan_endpoint.py tests/inference/test_lan_endpoint.py
git commit -m "feat(inference): LAN endpoint provider with cached health probe"
```

---

### Task 4: On-board local runner provider

**Files:**
- Create: `pantryatlas/inference/providers/local_runner.py`
- Test: `tests/inference/test_local_runner.py`

**Note:** Wraps the existing `GemmaRunner` (`.url`, `.is_healthy()`, `.start()` idempotent). Inject a fake runner + a `GemmaClient(transport=...)` in tests so no subprocess starts.

- [ ] **Step 1: Write the failing test**

```python
# tests/inference/test_local_runner.py
import httpx

from pantryatlas.gemma.client import GemmaClient
from pantryatlas.inference.providers.local_runner import LocalRunnerProvider


class _FakeRunner:
    url = "http://127.0.0.1:8080"

    def __init__(self, healthy: bool = True):
        self._healthy = healthy
        self.started = False

    def start(self) -> None:
        self.started = True

    def is_healthy(self) -> bool:
        return self._healthy


def _fake_chat(reply: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})
    return httpx.MockTransport(handler)


def test_generate_uses_injected_client():
    p = LocalRunnerProvider(
        runner=_FakeRunner(),
        client=GemmaClient(transport=_fake_chat("paprika")),
    )
    assert p.generate(system="s", user="u") == "paprika"


def test_is_available_tracks_runner_health():
    healthy = LocalRunnerProvider(runner=_FakeRunner(healthy=True),
                                  client=GemmaClient(transport=_fake_chat("x")))
    assert healthy.is_available() is True
    down = LocalRunnerProvider(runner=_FakeRunner(healthy=False),
                               client=GemmaClient(transport=_fake_chat("x")))
    assert down.is_available() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/inference/test_local_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: pantryatlas.inference.providers.local_runner`

- [ ] **Step 3: Write minimal implementation**

```python
# pantryatlas/inference/providers/local_runner.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/inference/test_local_runner.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add pantryatlas/inference/providers/local_runner.py tests/inference/test_local_runner.py
git commit -m "feat(inference): on-board local runner provider"
```

---

### Task 5: Provider registry with fallback

**Files:**
- Create: `pantryatlas/inference/registry.py`
- Test: `tests/inference/test_registry.py`

**Note:** `vision_generate` raises `VisionUnavailable` (not `NoProviderAvailable`) so the registry is drop-in compatible with `parse_shelf(image_bytes, gemma_client)` and the existing endpoint's `except VisionUnavailable -> 503`.

- [ ] **Step 1: Write the failing test**

```python
# tests/inference/test_registry.py
import httpx
import pytest

from pantryatlas.inference.provider import NoProviderAvailable
from pantryatlas.inference.registry import ProviderRegistry
from pantryatlas.navigator.vision import VisionUnavailable


class _StubProvider:
    def __init__(self, name, priority, caps, available=True, text_raises=None,
                 vision_raises=None, reply="ok", vision_reply="vis"):
        self.name = name
        self.kind = "lan"
        self.priority = priority
        self.capabilities = set(caps)
        self.enabled = True
        self._available = available
        self._text_raises = text_raises
        self._vision_raises = vision_raises
        self._reply = reply
        self._vision_reply = vision_reply
        self.text_calls = 0

    def is_available(self):
        return self._available

    def generate(self, system, user, **kwargs):
        self.text_calls += 1
        if self._text_raises:
            raise self._text_raises
        return self._reply

    def vision_generate(self, image_bytes, prompt, system):
        if self._vision_raises:
            raise self._vision_raises
        return self._vision_reply

    def info(self):
        from pantryatlas.inference.provider import ProviderInfo
        return ProviderInfo(self.name, self.kind, sorted(self.capabilities),
                            self.priority, self.enabled, self._available)


def test_generate_picks_lowest_priority_available():
    hi = _StubProvider("lan", 10, ["text"], reply="from-lan")
    lo = _StubProvider("local", 100, ["text"], reply="from-local")
    reg = ProviderRegistry([lo, hi])
    assert reg.generate(system="s", user="u") == "from-lan"
    assert lo.text_calls == 0


def test_generate_falls_back_when_first_unavailable():
    down = _StubProvider("lan", 10, ["text"], available=False)
    up = _StubProvider("local", 100, ["text"], reply="from-local")
    reg = ProviderRegistry([down, up])
    assert reg.generate(system="s", user="u") == "from-local"


def test_generate_falls_back_on_http_error():
    err = _StubProvider("lan", 10, ["text"],
                        text_raises=httpx.ConnectError("boom"))
    ok = _StubProvider("local", 100, ["text"], reply="from-local")
    reg = ProviderRegistry([err, ok])
    assert reg.generate(system="s", user="u") == "from-local"
    assert err.text_calls == 1


def test_generate_raises_when_none_available():
    reg = ProviderRegistry([_StubProvider("lan", 10, ["text"], available=False)])
    with pytest.raises(NoProviderAvailable):
        reg.generate(system="s", user="u")


def test_vision_generate_falls_back_then_raises():
    bad = _StubProvider("lan", 10, ["vision"],
                        vision_raises=VisionUnavailable("no mmproj"))
    good = _StubProvider("desk", 20, ["vision"], vision_reply="detected")
    reg = ProviderRegistry([bad, good])
    assert reg.vision_generate(b"img", "p", "s") == "detected"

    only_bad = ProviderRegistry([_StubProvider("lan", 10, ["vision"], available=False)])
    with pytest.raises(VisionUnavailable):
        only_bad.vision_generate(b"img", "p", "s")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/inference/test_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: pantryatlas.inference.registry`

- [ ] **Step 3: Write minimal implementation**

```python
# pantryatlas/inference/registry.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/inference/test_registry.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add pantryatlas/inference/registry.py tests/inference/test_registry.py
git commit -m "feat(inference): provider registry with capability routing + fallback"
```

---

### Task 6: Wire the registry into the navigator server

**Files:**
- Modify: `pantryatlas/navigator/server.py` (`create_app` signature ~183-192; vision endpoint ~405-426; add provider endpoints; production builder ~497)
- Test: `tests/navigator/test_providers_api.py`

**Note:** `create_app` gains `provider_registry: ProviderRegistry | None`. The vision endpoint passes the registry to `parse_shelf` (the registry implements `vision_generate`, so it is drop-in for a `GemmaClient`); when no registry/vision provider exists, `VisionUnavailable` -> existing 503 path. New REST endpoints manage providers and persist via `save_provider_config`.

- [ ] **Step 1: Write the failing test**

```python
# tests/navigator/test_providers_api.py
import io
from pathlib import Path

import httpx
import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from pantryatlas.gemma.client import GemmaClient
from pantryatlas.inference.providers.lan_endpoint import LanEndpointProvider
from pantryatlas.inference.registry import ProviderRegistry
from pantryatlas.navigator.server import create_app


class _InMemoryStore:
    def count(self) -> int:
        return 0


def _chat_transport(content: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
    return httpx.MockTransport(handler)


def _tiny_jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (200, 180, 120)).save(buf, format="JPEG")
    return buf.getvalue()


def _make_app(reg: ProviderRegistry, tmp_path: Path) -> TestClient:
    app = create_app(
        store=_InMemoryStore(),
        resolver=lambda raw: None,
        embed_fn=lambda texts: np.zeros((len(texts), 8)),
        pantry_path=tmp_path / "pantry.json",
        provider_registry=reg,
        providers_config_path=tmp_path / "providers.json",
    )
    return TestClient(app)


def _app(tmp_path: Path) -> TestClient:
    reg = ProviderRegistry([
        LanEndpointProvider(name="on-board", base_url="http://127.0.0.1:8080",
                            priority=100, capabilities=["text"],
                            client=GemmaClient(transport=_chat_transport("ok")),
                            health_check=lambda: True),
    ])
    return _make_app(reg, tmp_path)


def test_list_providers(tmp_path):
    client = _app(tmp_path)
    r = client.get("/navigator/providers")
    assert r.status_code == 200
    assert r.json()[0]["name"] == "on-board"


def test_add_lan_provider_persists(tmp_path):
    client = _app(tmp_path)
    r = client.post("/navigator/providers", json={
        "name": "desktop", "base_url": "http://192.168.1.50:8080", "multimodal": True,
    })
    assert r.status_code == 201
    names = [p["name"] for p in client.get("/navigator/providers").json()]
    assert "desktop" in names
    assert (tmp_path / "providers.json").exists()


def test_delete_provider(tmp_path):
    client = _app(tmp_path)
    client.post("/navigator/providers", json={
        "name": "desktop", "base_url": "http://192.168.1.50:8080", "multimodal": False,
    })
    assert client.delete("/navigator/providers/desktop").status_code == 200
    names = [p["name"] for p in client.get("/navigator/providers").json()]
    assert "desktop" not in names


def test_vision_endpoint_routes_through_registry(tmp_path):
    # The central architectural payoff: POST /vision/parse-shelf must run through
    # the registry's vision_generate, not the legacy app.state.vision_client.
    canned = '{"detected":[{"label":"flour","confidence":0.9}]}'
    reg = ProviderRegistry([
        LanEndpointProvider(
            name="desk", base_url="http://desk:8080", priority=10,
            capabilities=["text", "vision"],
            client=GemmaClient(base_url="http://desk:8080", transport=_chat_transport(canned)),
            health_check=lambda: True,
        ),
    ])
    client = _make_app(reg, tmp_path)
    r = client.post(
        "/navigator/vision/parse-shelf",
        files={"image": ("shelf.jpg", _tiny_jpeg(), "image/jpeg")},
    )
    assert r.status_code == 200
    assert "flour" in r.json()["items"]


def test_vision_endpoint_503_when_no_vision_provider(tmp_path):
    reg = ProviderRegistry([
        LanEndpointProvider(
            name="text-only", base_url="http://x:8080", priority=10,
            capabilities=["text"],
            client=GemmaClient(transport=_chat_transport("x")),
            health_check=lambda: True,
        ),
    ])
    client = _make_app(reg, tmp_path)
    r = client.post(
        "/navigator/vision/parse-shelf",
        files={"image": ("shelf.jpg", _tiny_jpeg(), "image/jpeg")},
    )
    assert r.status_code == 503
    assert r.json()["error"] == "vision_unavailable"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/navigator/test_providers_api.py -v`
Expected: FAIL — `create_app() got an unexpected keyword argument 'provider_registry'`

- [ ] **Step 3a: Add params to `create_app` and store on app.state**

In `pantryatlas/navigator/server.py`, extend the `create_app` signature (after `vision_client`):

```python
    vision_client: GemmaClient | None = None,
    provider_registry: "ProviderRegistry | None" = None,
    providers_config_path: Path | None = None,
) -> FastAPI:
```

Add the import near the top of the file:

```python
from pantryatlas.inference.registry import ProviderRegistry
from pantryatlas.inference.config import ProviderConfig, save_provider_config
from pantryatlas.inference.providers.lan_endpoint import LanEndpointProvider
```

After the existing `app.state.vision_client = vision_client` line, add:

```python
    app.state.provider_registry = provider_registry
    app.state.providers_config_path = providers_config_path
```

- [ ] **Step 3b: Add a Pydantic model and the provider endpoints**

Add the request model alongside the other `BaseModel` classes (~65-95):

```python
class ProviderIn(BaseModel):
    name: str
    base_url: str
    multimodal: bool = False
```

Add these routes inside `create_app` (before the final `return app`):

```python
    def _persist_providers() -> None:
        reg = app.state.provider_registry
        path = app.state.providers_config_path
        if reg is not None and path is not None:
            save_provider_config([p.to_config() for p in reg.all()], path)

    @app.get("/navigator/providers")
    def list_providers() -> list[dict[str, Any]]:
        reg = app.state.provider_registry
        if reg is None:
            return []
        return [
            {
                "name": i.name, "kind": i.kind, "capabilities": i.capabilities,
                "priority": i.priority, "enabled": i.enabled, "available": i.available,
            }
            for i in reg.providers_status()
        ]

    @app.post("/navigator/providers", status_code=201)
    def add_provider(body: ProviderIn) -> dict[str, Any]:
        reg = app.state.provider_registry
        if reg is None:
            raise HTTPException(status_code=503, detail="Provider registry not configured.")
        if reg.get(body.name) is not None:
            raise HTTPException(status_code=409, detail=f"Provider '{body.name}' already exists.")
        caps = ["text", "vision"] if body.multimodal else ["text"]
        reg.add(LanEndpointProvider(
            name=body.name, base_url=body.base_url, priority=10, capabilities=caps,
        ))
        _persist_providers()
        return {"name": body.name, "capabilities": caps}

    @app.post("/navigator/providers/{name}/test")
    def test_provider(name: str) -> dict[str, Any]:
        reg = app.state.provider_registry
        p = reg.get(name) if reg is not None else None
        if p is None:
            raise HTTPException(status_code=404, detail=f"No provider '{name}'.")
        return {"name": name, "available": p.force_probe()}

    @app.delete("/navigator/providers/{name}")
    def delete_provider(name: str) -> dict[str, str]:
        reg = app.state.provider_registry
        if reg is None or not reg.remove(name):
            raise HTTPException(status_code=404, detail=f"No provider '{name}'.")
        _persist_providers()
        return {"deleted": name}

    @app.put("/navigator/providers/order")
    def reorder_providers(ordered_names: list[str]) -> list[dict[str, Any]]:
        reg = app.state.provider_registry
        if reg is None:
            raise HTTPException(status_code=503, detail="Provider registry not configured.")
        reg.reorder(ordered_names)
        _persist_providers()
        return list_providers()
```

- [ ] **Step 3c: Route the vision endpoint through the registry**

Replace the `client = app.state.vision_client` block (~421-426) in `post_vision_parse_shelf` with:

```python
        registry = app.state.provider_registry
        client = app.state.vision_client  # backward-compat fallback
        backend = registry if registry is not None else client
        if backend is None:
            return JSONResponse(status_code=503, content={"error": "vision_unavailable"})
```

Then change the `parse_shelf(raw_bytes, client)` call to `parse_shelf(raw_bytes, backend)`. (The registry implements `vision_generate(image_bytes, prompt, system)`, identical to `GemmaClient`, so `parse_shelf` works unchanged and raises `VisionUnavailable` when no vision provider is available — already handled by the surrounding `except VisionUnavailable -> 503`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/navigator/test_providers_api.py -v`
Expected: PASS (5 tests — 3 CRUD + 2 vision-routing)

- [ ] **Step 5: Wire the production app builder**

In `_build_production_app()` (~497), build a registry from config and pass it in:

```python
    from pantryatlas.inference.config import DEFAULT_CONFIG_PATH, load_provider_config
    from pantryatlas.inference.registry import ProviderRegistry
    from pantryatlas.inference.providers.lan_endpoint import LanEndpointProvider
    from pantryatlas.inference.providers.local_runner import LocalRunnerProvider

    def _build_registry() -> ProviderRegistry:
        providers = []
        for cfg in load_provider_config(DEFAULT_CONFIG_PATH):
            if cfg.kind == "local":
                providers.append(LocalRunnerProvider(
                    name=cfg.name, priority=cfg.priority, enabled=cfg.enabled,
                    capabilities=cfg.capabilities,
                ))
            elif cfg.kind == "lan" and cfg.base_url:
                providers.append(LanEndpointProvider(
                    name=cfg.name, base_url=cfg.base_url, priority=cfg.priority,
                    enabled=cfg.enabled, capabilities=cfg.capabilities,
                ))
        return ProviderRegistry(providers)
```

The `create_app(...)` call at the end of `_build_production_app()` currently reads:

```python
    return create_app(
        store_factory=_make_production_store_factory(),
        resolver=_prod_resolver,
        embed_fn=_prod_embed,
        pantry_path=_DEFAULT_PANTRY_PATH,
    )
```

Change it to (add the last two kwargs):

```python
    return create_app(
        store_factory=_make_production_store_factory(),
        resolver=_prod_resolver,
        embed_fn=_prod_embed,
        pantry_path=_DEFAULT_PANTRY_PATH,
        provider_registry=_build_registry(),
        providers_config_path=DEFAULT_CONFIG_PATH,
    )
```

- [ ] **Step 6: Verify import is side-effect-free + full suite**

Run: `python -c 'from pantryatlas.navigator.server import app'`
Expected: no error, no DB/subprocess (LocalRunnerProvider does not start its runner until first use).
Run: `pytest -q`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add pantryatlas/navigator/server.py tests/navigator/test_providers_api.py
git commit -m "feat(navigator): wire provider registry into server + provider REST API"
```

---

### Task 7: "AI helpers" settings panel (frontend)

**Files:**
- Create: `web/src/components/AiHelpersPanel.tsx`
- Modify: `web/src/pages/Navigator.tsx` (mount the panel behind a settings toggle)
- Verify: browser (Vite dev server) — frontend has no unit-test harness; verify manually + via the existing screenshot script pattern.

**Note:** Match existing component style in `web/src/components/RecipeCard.tsx` (functional components, fetch to `/navigator/...`, plain CSS classes from `web/src/styles`). Keep it small and dependency-free.

**Scope shrink (intentional):** V1 UI exposes add / test / remove only. The `PUT /navigator/providers/order` (reorder) and enable/disable controls are deferred to a follow-up even though the API supports them — priority is settable via config file meanwhile. Note this in the commit message so it is a deliberate, recorded decision rather than an oversight.

- [ ] **Step 1: Create the panel component**

```tsx
// web/src/components/AiHelpersPanel.tsx
import { useEffect, useState } from "react";

type Provider = {
  name: string;
  kind: string;
  capabilities: string[];
  priority: number;
  enabled: boolean;
  available: boolean;
};

export function AiHelpersPanel() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [multimodal, setMultimodal] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    const r = await fetch("/navigator/providers");
    setProviders(await r.json());
  }

  useEffect(() => {
    refresh();
  }, []);

  async function addProvider(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const r = await fetch("/navigator/providers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, base_url: baseUrl, multimodal }),
    });
    if (!r.ok) {
      setError((await r.json()).detail ?? "Could not add helper");
      return;
    }
    setName("");
    setBaseUrl("");
    setMultimodal(false);
    refresh();
  }

  async function testProvider(n: string) {
    await fetch(`/navigator/providers/${encodeURIComponent(n)}/test`, { method: "POST" });
    refresh();
  }

  async function removeProvider(n: string) {
    await fetch(`/navigator/providers/${encodeURIComponent(n)}`, { method: "DELETE" });
    refresh();
  }

  return (
    <section className="ai-helpers">
      <h2>AI helpers on your network</h2>
      <p className="caption muted">
        Point PantryAtlas at a more powerful computer on your home network to do
        the heavy lifting. Nothing leaves your network.
      </p>

      <ul className="provider-list" role="list">
        {providers.map((p) => (
          <li key={p.name} className="provider-row">
            <span className={`dot ${p.available ? "dot--up" : "dot--down"}`} aria-hidden />
            <strong>{p.name}</strong>
            <span className="caption muted">
              {p.kind} · {p.capabilities.join(", ")} · priority {p.priority}
            </span>
            <button onClick={() => testProvider(p.name)}>Test</button>
            {p.kind !== "local" && (
              <button onClick={() => removeProvider(p.name)}>Remove</button>
            )}
          </li>
        ))}
      </ul>

      <form className="provider-form" onSubmit={addProvider}>
        <input
          placeholder="Name (e.g. kitchen-desktop)"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
        <input
          placeholder="http://192.168.1.50:8080"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          required
        />
        <label>
          <input
            type="checkbox"
            checked={multimodal}
            onChange={(e) => setMultimodal(e.target.checked)}
          />
          This helper can see photos (multimodal)
        </label>
        <button type="submit">Add helper</button>
        {error && <p className="error">{error}</p>}
      </form>
    </section>
  );
}
```

- [ ] **Step 2: Mount it in the Navigator page**

In `web/src/pages/Navigator.tsx`, import and render the panel behind a simple toggle (follow the file's existing state/section patterns):

```tsx
import { AiHelpersPanel } from "../components/AiHelpersPanel";
// ...inside the component:
const [showHelpers, setShowHelpers] = useState(false);
// ...in the JSX, near the page footer/header controls:
<button className="link" onClick={() => setShowHelpers((v) => !v)}>
  {showHelpers ? "Hide AI helpers" : "AI helpers"}
</button>
{showHelpers && <AiHelpersPanel />}
```

- [ ] **Step 3: Build the frontend**

Run: `cd web && npm install && npm run build`
Expected: build succeeds, no TypeScript errors.

- [ ] **Step 4: Manual browser verification**

Run the API: `python -m uvicorn pantryatlas.navigator.server:app --port 8080`
Then `cd web && npm run dev` and open the dev URL. Verify:
- Click "AI helpers" → panel shows the seeded `on-board` provider with a status dot.
- Add a helper with a bogus URL → it appears; click "Test" → status dot goes red (unreachable).
- Remove the helper → it disappears.
Confirm `~/.pantryatlas/providers.json` was created/updated after add/remove.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/AiHelpersPanel.tsx web/src/pages/Navigator.tsx
git commit -m "feat(web): AI helpers settings panel for the provider registry"
```

---

## Self-Review

- **Spec coverage:** provider registry (T5), on-board provider (T4), LAN provider (T3), capability/vision routing + fallback (T5), config persistence (T2), settings UI (T7), server wiring (T6). The spec's central integration — the vision endpoint routing **through** the registry — has an explicit regression test (`test_vision_endpoint_routes_through_registry`) plus a no-vision-provider 503 test (T6). The spec's "extend GemmaClient" item is intentionally dropped (superseded by T-014 `vision_generate` — see header note). Reserved provider kinds (`client`/`npu`/`hailo`) are present as comments only, per non-goals.
- **Type consistency:** `is_available()`, `force_probe()`, `vision_generate(image_bytes, prompt, system)`, `generate(system, user, **kwargs)`, `info() -> ProviderInfo`, `to_config() -> ProviderConfig` are used identically across `provider.py`, `lan_endpoint.py`, `local_runner.py`, and `registry.py`. The `/test` endpoint uses `force_probe()` (no private-attribute access). Registry methods `all/get/add/remove/reorder/generate/vision_generate/providers_status` match their call sites in Task 6.
- **No placeholders:** every code step contains full code; commands have expected output.

## Out of scope (future sub-projects, per spec)

Coral Yocto packaging + Gemma 3 270M swap; on-board NPU/LiteRT vision; client-in-browser (WebGPU) provider; mDNS discovery; genuine HailoRT vision provider. The registry leaves labeled `kind`/capability slots for these.
