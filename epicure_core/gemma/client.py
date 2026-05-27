"""Gemma 4 HTTP client over llama-server's OpenAI-compatible API."""
import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_MODEL_NAME = "gemma-4-E4B-it"  # informational; llama-server ignores
DEFAULT_TIMEOUT_S = 60.0


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
        max_tokens: int = 512,
        temperature: float = 0.2,
    ) -> str:
        """Generate a plain-text completion via the chat-completions endpoint.

        Uses Gemma 4's native system role — sends system prompt as standard
        {"role": "system", "content": "..."} message.

        Args:
            system: System prompt / role instructions.
            user: User message / query.
            max_tokens: Maximum tokens in the response (default: 512).
            temperature: Sampling temperature (default: 0.2).

        Returns:
            The assistant's response text.

        Raises:
            httpx.HTTPStatusError: If the server returns a non-2xx status.
        """
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
        # Standard OpenAI-compatible response shape: choices[0].message.content
        return body["choices"][0]["message"]["content"]
