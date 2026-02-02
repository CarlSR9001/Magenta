"""
Minimal configuration loader for Magenta.

- Loads config.yaml
- Allows env var overrides for secrets
"""

from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

logger = logging.getLogger(__name__)


class ConfigLoader:
    """Load config from YAML and optionally override with env vars."""

    def __init__(self, config_path: str = "config.yaml") -> None:
        self.config_path = Path(config_path)
        self._config: Dict[str, Any] = {}
        self._load_config()

    def _load_config(self) -> None:
        if not self.config_path.exists():
            raise FileNotFoundError(
                f"Config file not found: {self.config_path}\n"
                f"Copy config.example.yaml to config.yaml and fill it in."
            )
        try:
            with self.config_path.open("r", encoding="utf-8") as handle:
                self._config = yaml.safe_load(handle) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid YAML in {self.config_path}: {exc}") from exc

    def get(self, key: str, default: Any = None) -> Any:
        keys = key.split(".")
        value: Any = self._config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    def get_with_env(self, key: str, env_var: str, default: Any = None) -> Any:
        env_value = os.getenv(env_var)
        if env_value is not None:
            return env_value
        config_value = self.get(key)
        if config_value is not None:
            return config_value
        return default

    def get_required(self, key: str, env_var: Optional[str] = None) -> Any:
        value = self.get_with_env(key, env_var) if env_var else self.get(key)
        if value is None:
            source = f"config key '{key}'"
            if env_var:
                source += f" or env var '{env_var}'"
            raise ValueError(f"Required configuration value missing: {source}")
        return value

    def get_section(self, section: str) -> Dict[str, Any]:
        return self.get(section, {})


_config_instance: Optional[ConfigLoader] = None


def get_config(config_path: str = "config.yaml") -> ConfigLoader:
    global _config_instance
    if _config_instance is None:
        effective_path = config_path
        if config_path == "config.yaml":
            local_path = Path("config.local.yaml")
            if local_path.exists():
                effective_path = str(local_path)
        _config_instance = ConfigLoader(effective_path)
    return _config_instance


def reload_config() -> None:
    global _config_instance
    if _config_instance is not None:
        _config_instance._load_config()


# ---- Typed accessors ----

def get_letta_config() -> Dict[str, Any]:
    config = get_config()
    return {
        "api_key": config.get_required("letta.api_key", "LETTA_API_KEY"),
        "timeout": config.get("letta.timeout", 600),
        "agent_id": config.get_required("letta.agent_id", "LETTA_AGENT_ID"),
        "base_url": config.get("letta.base_url"),
    }


def get_bluesky_config() -> Dict[str, Any]:
    config = get_config()
    return {
        "username": config.get_required("bluesky.username", "BSKY_USERNAME"),
        "password": config.get_required("bluesky.password", "BSKY_PASSWORD"),
        "pds_uri": config.get("bluesky.pds_uri", "https://bsky.social"),
    }


def get_elevenlabs_config() -> Dict[str, Any]:
    config = get_config()
    max_audio_seconds_env = os.getenv("ELEVENLABS_MAX_AUDIO_SECONDS")
    max_audio_seconds = None
    if max_audio_seconds_env:
        try:
            max_audio_seconds = float(max_audio_seconds_env)
        except ValueError:
            max_audio_seconds = None
    return {
        "api_key": config.get("elevenlabs.api_key", os.getenv("ELEVENLABS_API_KEY", "")),
        "voice_id": config.get("elevenlabs.voice_id", os.getenv("ELEVENLABS_VOICE_ID", "")),
        "max_audio_seconds": config.get("elevenlabs.max_audio_seconds", max_audio_seconds or 59.0),
    }


def get_relay_audio_config() -> Dict[str, Any]:
    config = get_config()
    return {
        "url": config.get("relay_audio.url", os.getenv("RELAY_AUDIO_URL", "")),
        "token": config.get("relay_audio.token", os.getenv("RELAY_AUDIO_TOKEN", "")),
    }


def get_moltbook_config() -> Dict[str, Any]:
    config = get_config()
    return {
        "api_key": config.get("moltbook.api_key", os.getenv("MOLTBOOK_API_KEY", "")),
        "agent_name": config.get("moltbook.agent_name", ""),
        "agent_description": config.get("moltbook.agent_description", ""),
    }
