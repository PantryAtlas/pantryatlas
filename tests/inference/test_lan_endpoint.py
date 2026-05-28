import httpx
import pytest

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
    with pytest.raises(CapabilityUnavailable) as exc_info:
        p.vision_generate(b"jpegbytes", "prompt", "system")
    assert exc_info.value.capability == "vision"


def test_is_available_reflects_health_and_enabled():
    p = LanEndpointProvider(
        name="peer", base_url="http://peer:8080", priority=10,
        capabilities=["text"], client=GemmaClient(transport=_fake_chat("x")),
        health_check=lambda: True,
    )
    assert p.is_available() is True
    p.enabled = False
    assert p.is_available() is False
