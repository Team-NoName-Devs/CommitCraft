"""Tests for application configuration and environment overrides."""

import json
from pathlib import Path
import pytest
from pydantic import ValidationError

from commitcraft.config import (
    AppConfig,
    REQUIRED_MODEL,
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_READ_TIMEOUT,
    DEFAULT_MAX_CORRECTIONS,
)


def test_app_config_defaults():
    """Test that default AppConfig has the expected non-negotiable defaults."""
    cfg = AppConfig()
    assert cfg.ollama_base_url == DEFAULT_OLLAMA_BASE_URL
    assert cfg.connect_timeout == DEFAULT_CONNECT_TIMEOUT
    assert cfg.read_timeout == DEFAULT_READ_TIMEOUT
    assert cfg.max_correction_attempts == DEFAULT_MAX_CORRECTIONS
    assert cfg.color is True
    assert cfg.git_timeout == 30.0
    assert cfg.model == REQUIRED_MODEL
    assert cfg.model == "llama3.2:3b"


def test_app_config_model_fixed_invariant():
    """Verify that model is a fixed read-only property and cannot be overridden."""
    cfg = AppConfig()
    assert cfg.model == "llama3.2:3b"
    # Setting model should raise AttributeError because it's a property without a setter
    with pytest.raises(AttributeError):
        cfg.model = "gpt-4"


def test_app_config_url_validation():
    """Test Ollama base URL validation and trailing slash normalization."""
    # Normalizes trailing slash
    cfg1 = AppConfig(ollama_base_url="http://localhost:11434/")
    assert cfg1.ollama_base_url == "http://localhost:11434"

    # HTTPS is accepted
    cfg2 = AppConfig(ollama_base_url="https://remote-ollama.internal:11434")
    assert cfg2.ollama_base_url == "https://remote-ollama.internal:11434"

    # Invalid protocols rejected
    with pytest.raises(ValidationError):
        AppConfig(ollama_base_url="ftp://localhost:11434")

    with pytest.raises(ValidationError):
        AppConfig(ollama_base_url="localhost:11434")


def test_app_config_load_nonexistent_file(temp_dir: Path):
    """Test loading configuration when the file does not exist returns defaults."""
    cfg = AppConfig.load(temp_dir / "nonexistent_config.json")
    assert cfg.ollama_base_url == DEFAULT_OLLAMA_BASE_URL
    assert cfg.read_timeout == DEFAULT_READ_TIMEOUT


def test_app_config_load_corrupted_file(temp_dir: Path):
    """Test loading configuration when file contains invalid JSON falls back safely."""
    bad_file = temp_dir / "corrupted_config.json"
    bad_file.write_text("{ not valid json !!! }", encoding="utf-8")

    cfg = AppConfig.load(bad_file)
    assert cfg.ollama_base_url == DEFAULT_OLLAMA_BASE_URL
    assert cfg.connect_timeout == DEFAULT_CONNECT_TIMEOUT


def test_app_config_save_and_load(temp_dir: Path):
    """Test saving configuration to disk and loading it back."""
    target_path = temp_dir / "subdir" / "my_config.json"
    cfg = AppConfig(
        ollama_base_url="http://192.168.1.50:11434",
        connect_timeout=12.5,
        read_timeout=240.0,
        max_correction_attempts=5,
        color=False,
        git_timeout=45.0,
    )
    saved_path = cfg.save(target_path)
    assert saved_path == target_path
    assert saved_path.is_file()

    # Load back
    loaded_cfg = AppConfig.load(target_path)
    assert loaded_cfg.ollama_base_url == "http://192.168.1.50:11434"
    assert loaded_cfg.connect_timeout == 12.5
    assert loaded_cfg.read_timeout == 240.0
    assert loaded_cfg.max_correction_attempts == 5
    assert loaded_cfg.color is False
    assert loaded_cfg.git_timeout == 45.0
    assert loaded_cfg.model == "llama3.2:3b"


def test_app_config_env_overrides(monkeypatch: pytest.MonkeyPatch, temp_dir: Path):
    """Test environment variable overrides for Ollama settings."""
    monkeypatch.setenv("COMMITCRAFT_OLLAMA_URL", "http://env-host:11434")
    monkeypatch.setenv("COMMITCRAFT_CONNECT_TIMEOUT", "15.0")
    monkeypatch.setenv("COMMITCRAFT_READ_TIMEOUT", "300.0")

    cfg = AppConfig.load(temp_dir / "none.json")
    assert cfg.ollama_base_url == "http://env-host:11434"
    assert cfg.connect_timeout == 15.0
    assert cfg.read_timeout == 300.0


def test_app_config_env_overrides_invalid_float(monkeypatch: pytest.MonkeyPatch, temp_dir: Path):
    """Test that invalid float in environment variables does not crash loading."""
    monkeypatch.setenv("COMMITCRAFT_CONNECT_TIMEOUT", "not-a-number")
    monkeypatch.setenv("COMMITCRAFT_READ_TIMEOUT", "invalid")

    cfg = AppConfig.load(temp_dir / "none.json")
    # Should safely retain default values
    assert cfg.connect_timeout == DEFAULT_CONNECT_TIMEOUT
    assert cfg.read_timeout == DEFAULT_READ_TIMEOUT
