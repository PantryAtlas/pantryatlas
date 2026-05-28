"""Basic tests for GemmaClient.generate() using mocked httpx transport."""
import json

import httpx
import pytest

from pantryatlas.gemma.client import GemmaClient


def _fake_server(expected_check=None):
    """Returns an httpx MockTransport that pretends to be llama-server's chat endpoint.

    Args:
        expected_check: Optional callable that receives the request body dict
                       for assertions.

    Returns:
        httpx.MockTransport that returns standard OpenAI-compatible response.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if expected_check:
            expected_check(body)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": "cumin, paprika, thyme"}}
                ]
            },
        )

    return httpx.MockTransport(handler)


def test_generate_returns_text():
    """Test that generate() returns the assistant's response text."""
    client = GemmaClient(transport=_fake_server())
    out = client.generate(system="you are a chef", user="name three spices")
    assert out == "cumin, paprika, thyme"
    client.close()


def test_request_uses_native_system_role():
    """Test that the HTTP request body uses native system role (not shim)."""
    captured = {}

    def check(body):
        captured["messages"] = body["messages"]

    client = GemmaClient(transport=_fake_server(expected_check=check))
    client.generate(system="you are a chef", user="hello")
    msgs = captured["messages"]
    assert msgs[0] == {"role": "system", "content": "you are a chef"}
    assert msgs[1] == {"role": "user", "content": "hello"}
    client.close()


def test_context_manager_closes():
    """Test that context manager works and closes without error."""
    with GemmaClient(transport=_fake_server()) as client:
        assert client.generate(system="s", user="u") == "cumin, paprika, thyme"
    # implicit close should not raise


def test_raises_on_non_200():
    """Test that non-2xx responses raise httpx.HTTPStatusError."""

    def handler(request):
        return httpx.Response(500, text="server died")

    client = GemmaClient(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        client.generate(system="s", user="u")
    client.close()
