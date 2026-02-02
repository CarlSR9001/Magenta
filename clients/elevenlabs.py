"""Minimal ElevenLabs HTTP client helpers."""

from __future__ import annotations

from typing import Optional

import requests

from config_loader import get_elevenlabs_config


def _headers(api_key: Optional[str] = None) -> dict:
    cfg = get_elevenlabs_config()
    key = api_key or cfg.get("api_key")
    if not key:
        raise ValueError("ELEVENLABS_API_KEY is not configured")
    return {"xi-api-key": key}


def list_voices(api_key: Optional[str] = None) -> dict:
    resp = requests.get(
        "https://api.elevenlabs.io/v1/voices",
        headers=_headers(api_key),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def text_to_speech(
    text: str,
    voice_id: Optional[str] = None,
    model_id: str = "eleven_turbo_v2_5",
    api_key: Optional[str] = None,
) -> bytes:
    cfg = get_elevenlabs_config()
    resolved_voice_id = voice_id or cfg.get("voice_id")
    if not resolved_voice_id:
        raise ValueError("Missing ElevenLabs voice_id (set in config or pass explicitly)")

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{resolved_voice_id}"
    resp = requests.post(
        url,
        headers={**_headers(api_key), "Content-Type": "application/json"},
        json={
            "text": text,
            "model_id": model_id,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.content
