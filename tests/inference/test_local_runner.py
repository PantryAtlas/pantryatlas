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
