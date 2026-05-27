"""Gemma 4 HTTP client over llama-server's OpenAI-compatible API."""
import json
import re

import httpx
import jsonschema

DEFAULT_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_MODEL_NAME = "gemma-4-E4B-it"  # informational; llama-server ignores
DEFAULT_TIMEOUT_S = 60.0


class RepairExhaustedError(RuntimeError):
    """Raised when relaxed-JSON generate exhausts all repair retries."""

    def __init__(self, last_response: str, last_error: Exception):
        self.last_response = last_response
        self.last_error = last_error
        super().__init__(f"JSON repair exhausted after retries; last error: {last_error}")


class GemmaClient:
    """Plain-text Gemma 4 chat client over llama-server's OpenAI-compatible API.

    Uses Gemma 4's native system role per T-001 verification — no role-prefix
    shim needed. Targets the standard OpenAI-compatible chat-completions endpoint.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        transport: httpx.BaseTransport | None = None,
    ):
        """Initialize the Gemma client.

        Args:
            base_url: Base URL of the llama-server instance (default: http://127.0.0.1:8080).
            timeout_s: Request timeout in seconds (default: 60.0).
            transport: Optional httpx.BaseTransport for testing/mocking.
        """
        self._base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout_s, transport=transport)

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, *_) -> None:
        """Context manager exit."""
        self.close()

    def generate(
        self,
        system: str,
        user: str,
        schema: dict | None = None,
        strict: bool = False,
        max_tokens: int = 512,
        temperature: float = 0.2,
        max_repair_retries: int = 2,
    ) -> str | dict:
        """Generate a response, optionally schema-constrained.

        Uses Gemma 4's native system role — sends system prompt as standard
        {"role": "system", "content": "..."} message.

        Args:
            system: System prompt / role instructions.
            user: User message / query.
            schema: Optional JSON Schema dict. When provided, the response is
                parsed as JSON matching this schema and returned as dict (not str).
            strict: When True, use llama.cpp's grammar-constrained generation
                by passing the schema as a GBNF grammar in the request. When
                False (default), the schema is included in the prompt and the
                response is validated + repaired up to max_repair_retries times.

                WARNING: strict=True is much slower on Pi 5 — local-llm-ops T9
                measured ~6 min/batch for json_schema strict:true mode. Prefer
                the relaxed (strict=False) path unless the output absolutely
                cannot tolerate the parse-and-retry overhead.
            max_tokens: Maximum tokens in the response (default: 512).
            temperature: Sampling temperature (default: 0.2).
            max_repair_retries: Maximum repair attempts for relaxed schema mode
                (default: 2, meaning 3 total attempts: 1 initial + 2 repairs).

        Returns:
            When schema is None: the assistant's response text (str).
            When schema is not None: a dict parsed and validated against the schema.

        Raises:
            httpx.HTTPStatusError: If the server returns a non-2xx status.
            RepairExhaustedError: When relaxed mode exhausts all repair retries
                without getting valid JSON matching the schema.
            jsonschema.ValidationError: Propagated if strict mode receives JSON
                that doesn't match the schema.
        """
        if schema is None:
            # Plain-text path: no schema, return str
            return self._generate_text(system, user, max_tokens, temperature)

        if strict:
            # Strict path: grammar-constrained generation
            return self._generate_strict(
                system, user, schema, max_tokens, temperature
            )

        # Relaxed path: prompt-based schema with repair loop
        return self._generate_relaxed(
            system, user, schema, max_tokens, temperature, max_repair_retries
        )

    def _generate_text(
        self, system: str, user: str, max_tokens: int, temperature: float
    ) -> str:
        """Generate plain text (no schema)."""
        payload = {
            "model": DEFAULT_MODEL_NAME,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        r = self._client.post(f"{self._base_url}/v1/chat/completions", json=payload)
        r.raise_for_status()
        body = r.json()
        return body["choices"][0]["message"]["content"]

    def _generate_relaxed(
        self,
        system: str,
        user: str,
        schema: dict,
        max_tokens: int,
        temperature: float,
        max_repair_retries: int,
    ) -> dict:
        """Generate JSON with prompt-based schema and repair loop."""
        schema_str = json.dumps(schema, indent=2)
        augmented_system = (
            f"{system}\n\n"
            f"Respond with a JSON object matching this schema:\n"
            f"{schema_str}\n"
            f"Output only the JSON object — no prose, no markdown fences."
        )

        messages = [
            {"role": "system", "content": augmented_system},
            {"role": "user", "content": user},
        ]

        last_response = None
        last_error = None

        for attempt in range(1 + max_repair_retries):
            payload = {
                "model": DEFAULT_MODEL_NAME,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            r = self._client.post(
                f"{self._base_url}/v1/chat/completions", json=payload
            )
            r.raise_for_status()
            body = r.json()
            response_text = body["choices"][0]["message"]["content"]
            last_response = response_text

            # Try to parse the response as JSON
            parsed = self._parse_json(response_text)
            if parsed is not None:
                # Try to validate against schema
                try:
                    jsonschema.validate(parsed, schema)
                    return parsed  # Success!
                except jsonschema.ValidationError as e:
                    last_error = e
                    # Fall through to repair logic
            else:
                last_error = ValueError(
                    "Could not parse response as JSON (no {...} block found)"
                )

            # If we've exhausted retries, raise
            if attempt >= max_repair_retries:
                raise RepairExhaustedError(last_response, last_error)

            # Append a repair message to the conversation
            messages.append({"role": "assistant", "content": response_text})
            repair_msg = (
                f"The JSON you provided is invalid. Error: {last_error}. "
                f"Please provide a corrected JSON object matching the schema."
            )
            messages.append({"role": "user", "content": repair_msg})

        # Should never reach here, but satisfy type checker
        raise RepairExhaustedError(last_response, last_error)

    def _generate_strict(
        self, system: str, user: str, schema: dict, max_tokens: int, temperature: float
    ) -> dict:
        """Generate JSON with grammar-constrained generation."""
        payload = {
            "model": DEFAULT_MODEL_NAME,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            # AC-5: Add grammar field for strict mode.
            # TODO: implement proper schema-to-GBNF conversion.
            # For now, pass a placeholder GBNF that matches generic JSON.
            "grammar": _placeholder_json_grammar(),
        }
        r = self._client.post(f"{self._base_url}/v1/chat/completions", json=payload)
        r.raise_for_status()
        body = r.json()
        response_text = body["choices"][0]["message"]["content"]
        parsed = json.loads(response_text)
        jsonschema.validate(parsed, schema)
        return parsed

    @staticmethod
    def _parse_json(text: str) -> dict | None:
        """Try to extract and parse JSON from text.

        First attempts direct json.loads(); if that fails, tries to extract
        the first {...} block via regex.

        Returns None if parsing fails.
        """
        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to extract a {...} block
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        return None


def _placeholder_json_grammar() -> str:
    """Return a placeholder GBNF grammar matching generic JSON objects.

    This is a minimal GBNF that allows any JSON object. In production,
    we should convert the actual schema to a more specific grammar.

    TODO: implement proper schema-to-GBNF conversion.
    """
    # Simplified JSON GBNF that accepts any JSON value at the root
    hex_digit = "[0-9a-fA-F]"
    return (
        r"""
root ::= object
value ::= object | array | string | number | ("true" | "false" | "null") ws
object ::= "{" ws (string ":" ws value ("," ws string ":" ws value)*)? "}" ws
array ::= "[" ws (value ("," ws value)*)? "]" ws
string ::= "\"" (([^"\\] | "\\" (["\\/bfnrt] | "u" """
        + hex_digit * 4
        + r""")))*  "\""
number ::= ("-"? ([0-9] | [1-9] [0-9]*)) ("." [0-9]+)? ([eE] [-+]? [0-9]+)?
ws ::= ([ \t\n] ws)?
"""
    )
