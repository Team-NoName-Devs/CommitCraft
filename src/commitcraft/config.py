"""Configuration management for CommitCraft."""

import json
import os
from pathlib import Path
from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator


# Mandatory non-negotiable runtime model
REQUIRED_MODEL: str = "llama3.2:3b"
DEFAULT_OLLAMA_BASE_URL: str = "http://localhost:11434"
DEFAULT_CONNECT_TIMEOUT: float = 5.0
DEFAULT_READ_TIMEOUT: float = 120.0
DEFAULT_MAX_CORRECTIONS: int = 3


def get_default_config_path() -> Path:
    """Return default user configuration file path."""
    config_dir = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "commitcraft"
    return config_dir / "config.json"


class AppConfig(BaseModel):
    """Runtime application configuration."""

    ollama_base_url: str = Field(
        default=DEFAULT_OLLAMA_BASE_URL,
        description="Base URL for local Ollama service",
    )
    connect_timeout: float = Field(
        default=DEFAULT_CONNECT_TIMEOUT,
        description="Connection timeout for Ollama API in seconds",
    )
    read_timeout: float = Field(
        default=DEFAULT_READ_TIMEOUT,
        description="Read timeout for Ollama inference in seconds",
    )
    max_correction_attempts: int = Field(
        default=DEFAULT_MAX_CORRECTIONS,
        description="Maximum correction attempts for invalid model output",
    )
    color: bool = Field(default=True, description="Enable rich colored output in terminal")
    git_timeout: float = Field(default=30.0, description="Native Git subprocess timeout in seconds")

    @property
    def model(self) -> str:
        """The required model is fixed to llama3.2:3b. No substitutions allowed."""
        return REQUIRED_MODEL

    @field_validator("ollama_base_url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if not v.startswith(("http://", "https://")):
            raise ValueError("ollama_base_url must start with http:// or https://")
        return v

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "AppConfig":
        """Load configuration from file or environment variables."""
        target_path = path or get_default_config_path()
        data: dict[str, Any] = {}

        if target_path.is_file():
            try:
                with open(target_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}

        # Environment variable overrides
        if "COMMITCRAFT_OLLAMA_URL" in os.environ:
            data["ollama_base_url"] = os.environ["COMMITCRAFT_OLLAMA_URL"]
        if "COMMITCRAFT_CONNECT_TIMEOUT" in os.environ:
            try:
                data["connect_timeout"] = float(os.environ["COMMITCRAFT_CONNECT_TIMEOUT"])
            except ValueError:
                pass
        if "COMMITCRAFT_READ_TIMEOUT" in os.environ:
            try:
                data["read_timeout"] = float(os.environ["COMMITCRAFT_READ_TIMEOUT"])
            except ValueError:
                pass

        return cls(**data)

    def save(self, path: Optional[Path] = None) -> Path:
        """Save configuration to disk."""
        target_path = path or get_default_config_path()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(self.model_dump_json(indent=2))
        return target_path
