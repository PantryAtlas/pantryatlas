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
