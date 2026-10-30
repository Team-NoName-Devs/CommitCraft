"""HTTP client for communicating with local Ollama runtime."""

from typing import Any, Optional
import httpx

from commitcraft.config import DEFAULT_CONNECT_TIMEOUT, DEFAULT_OLLAMA_BASE_URL, DEFAULT_READ_TIMEOUT, REQUIRED_MODEL
from commitcraft.errors import ModelResponseError, ModelUnavailableError


class OllamaClient:
    """Client for local Ollama service running the required llama3.2:3b model."""

    def __init__(
        self,
        base_url: str = DEFAULT_OLLAMA_BASE_URL,
        model: str = REQUIRED_MODEL,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        client: Optional[httpx.Client] = None,
    ):
        self.base_url = base_url.rstrip("/")
        # Mandatory: required model cannot be substituted
        self.model = model
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self._client = client

    def _get_client(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        return httpx.Client(
            timeout=httpx.Timeout(
                connect=self.connect_timeout,
                read=self.read_timeout,
                write=30.0,
                pool=10.0,
            )
        )

    def check_health(self) -> None:
        """Verify Ollama is reachable and the required llama3.2:3b model is available."""
        endpoint = f"{self.base_url}/api/tags"
        client = self._get_client()
        try:
            resp = client.get(endpoint)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise ModelUnavailableError(
                f"Cannot connect to Ollama service at {self.base_url}: {e}",
                resolution="Ensure Ollama is running ('ollama serve') on localhost.",
            ) from e
        except httpx.HTTPError as e:
            raise ModelUnavailableError(
                f"Ollama returned HTTP error from {endpoint}: {e}",
                resolution="Verify Ollama health and check endpoint configuration.",
            ) from e
        except Exception as e:
            raise ModelUnavailableError(
                f"Failed to query Ollama models: {e}",
                resolution="Check Ollama service status.",
            ) from e

        models = [m.get("name", "") for m in data.get("models", [])]
        model_found = any(
            m == self.model
            or m.startswith(f"{self.model}:")
            or m.startswith(f"{self.model}-")
            or f"{self.model}:" in m
            for m in models
        )

        if not model_found:
            raise ModelUnavailableError(
                f"Required model '{self.model}' is not installed in Ollama. Found: {models}",
                resolution=f"Run 'ollama pull {self.model}' to download the required model.",
            )

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        format_json: bool = True,
    ) -> str:
        """Call Ollama /api/chat with structured output mode."""
        endpoint = f"{self.base_url}/api/chat"
        client = self._get_client()

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }
        if format_json:
            payload["format"] = "json"

        try:
            resp = client.post(endpoint, json=payload)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise ModelUnavailableError(
                f"Lost connection to Ollama at {self.base_url}: {e}",
                resolution="Ensure Ollama service remains running.",
            ) from e
        except httpx.ReadTimeout as e:
            raise ModelResponseError(
                f"Ollama inference timed out after {self.read_timeout} seconds: {e}",
                resolution="Increase read_timeout in config or verify GPU/CPU load.",
            ) from e
        except httpx.HTTPStatusError as e:
            raise ModelResponseError(
                f"Ollama API error ({e.response.status_code}): {e.response.text}",
                resolution="Check Ollama logs for details on the error.",
            ) from e
        except Exception as e:
            raise ModelResponseError(
                f"Failed to communicate with Ollama: {e}",
                resolution="Verify Ollama service status and retry.",
            ) from e

        message_obj = data.get("message")
        if not message_obj or "content" not in message_obj:
            raise ModelResponseError(
                "Ollama response missing 'message.content'.",
                resolution="Verify Ollama version and response format.",
            )

        return message_obj["content"]
