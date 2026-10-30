"""Tests for Ollama HTTP client with mock transports."""

import json
import httpx
import pytest

from commitcraft.errors import ModelResponseError, ModelUnavailableError
from commitcraft.model_client import OllamaClient


def test_ollama_health_check_success():
    """Test successful health check when required llama3.2:3b model is present."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"models": [{"name": "llama3.2:3b"}]},
        )

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    ollama = OllamaClient(client=client)

    # Should not raise
    ollama.check_health()


def test_ollama_missing_required_model():
    """Test health check fails when required model is not installed."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"models": [{"name": "mistral:7b"}, {"name": "codellama:7b"}]},
        )

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    ollama = OllamaClient(client=client)

    with pytest.raises(ModelUnavailableError) as exc_info:
        ollama.check_health()
    assert "Required model 'llama3.2:3b' is not installed" in str(exc_info.value)
    assert "ollama pull llama3.2:3b" in exc_info.value.resolution


def test_ollama_connection_refused():
    """Test connection failure raises ModelUnavailableError."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    ollama = OllamaClient(client=client)

    with pytest.raises(ModelUnavailableError) as exc_info:
        ollama.check_health()
    assert "Cannot connect to Ollama service" in str(exc_info.value)


def test_ollama_chat_completion_success():
    """Test successful chat completion returning JSON content."""
    expected_content = json.dumps({"summary": "test", "groups": []})

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        payload = json.loads(request.content)
        assert payload["model"] == "llama3.2:3b"
        assert payload["format"] == "json"
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": expected_content}},
        )

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    ollama = OllamaClient(client=client)

    content = ollama.chat_completion([{"role": "user", "content": "hi"}])
    assert content == expected_content


def test_ollama_chat_timeout():
    """Test chat timeout raises ModelResponseError."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Read timed out")

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    ollama = OllamaClient(client=client)

    with pytest.raises(ModelResponseError) as exc_info:
        ollama.chat_completion([{"role": "user", "content": "hi"}])
    assert "timed out" in str(exc_info.value)
