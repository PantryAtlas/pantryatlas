"""Tests for GemmaClient schema-constrained generation and repair loop."""
import json

import httpx
import pytest

from epicure_core.gemma.client import GemmaClient, RepairExhaustedError

SIMPLE_SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "count": {"type": "integer"}},
    "required": ["name", "count"],
}


def _scripted_server(responses):
    """Return an httpx.MockTransport that yields each response in sequence.

    Args:
        responses: List of response bodies (str) or httpx.Response objects.
                   If str, wraps it in the standard OpenAI-compatible format.

    Returns:
        (transport, handler) tuple.
    """
    it = iter(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        nxt = next(it)
        if isinstance(nxt, str):
            return httpx.Response(
                200,
                json={"choices": [{"message": {"role": "assistant", "content": nxt}}]},
            )
        return nxt  # already an httpx.Response

    return httpx.MockTransport(handler), handler


def test_relaxed_repair_succeeds_after_one_retry():
    """Test that relaxed mode retries on invalid JSON and succeeds with valid JSON."""
    valid = json.dumps({"name": "garlic", "count": 3})
    transport, _ = _scripted_server(["not even close to json", valid])
    client = GemmaClient(transport=transport)
    out = client.generate(
        system="be helpful", user="give me an ingredient", schema=SIMPLE_SCHEMA
    )
    assert isinstance(out, dict)
    assert out == {"name": "garlic", "count": 3}
    client.close()


def test_relaxed_repair_exhausted_raises():
    """Test that relaxed mode raises RepairExhaustedError after exhausting retries."""
    transport, _ = _scripted_server(["nope", "still nope", "nope nope"])
    client = GemmaClient(transport=transport)
    with pytest.raises(RepairExhaustedError) as exc_info:
        client.generate(
            system="be helpful", user="give me an ingredient", schema=SIMPLE_SCHEMA
        )
    assert exc_info.value.last_response == "nope nope"
    client.close()


def test_strict_mode_adds_grammar_field():
    """Test that strict=True adds a 'grammar' field to the request body."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps({"name": "x", "count": 1}),
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    client = GemmaClient(transport=transport)
    client.generate(
        system="be helpful",
        user="give me one",
        schema=SIMPLE_SCHEMA,
        strict=True,
    )
    assert (
        "grammar" in captured["body"]
    ), f"strict=True did not add 'grammar' field; body keys: {list(captured['body'].keys())}"
    client.close()


def test_schema_none_returns_string():
    """Test that when schema=None, generate() returns a string."""
    transport, _ = _scripted_server(["just plain text"])
    client = GemmaClient(transport=transport)
    out = client.generate(system="s", user="u", schema=None)
    assert isinstance(out, str)
    assert out == "just plain text"
    client.close()


def test_relaxed_mode_validates_against_schema():
    """Test that valid JSON that doesn't match schema is rejected and repaired."""
    invalid_schema = json.dumps({"name": "john", "count": "not-a-number"})
    valid_schema = json.dumps({"name": "john", "count": 42})
    transport, _ = _scripted_server([invalid_schema, valid_schema])
    client = GemmaClient(transport=transport)
    out = client.generate(
        system="s", user="u", schema=SIMPLE_SCHEMA, strict=False
    )
    assert out == {"name": "john", "count": 42}
    client.close()


def test_docstring_warns_about_strict_latency():
    """Test that the docstring contains both 'strict=True' and '6 min'."""
    doc = GemmaClient.generate.__doc__
    assert "strict=True" in doc, "Docstring does not mention 'strict=True'"
    assert "6 min" in doc, "Docstring does not mention '6 min'"
