"""Relay audio generation requests to an external service."""

from __future__ import annotations

from typing import Optional, List, Dict, Any

import requests

from config_loader import get_relay_audio_config


def relay_audio(
    text: Optional[str] = None,
    dialogue: Optional[List[Dict[str, Any]]] = None,
    voice_id: Optional[str] = None,
    model_id: str = "eleven_turbo_v2_5",
    caption: Optional[str] = None,
    url: Optional[str] = None,
    token: Optional[str] = None,
) -> str:
    if not text and not dialogue:
        raise ValueError("Provide 'text' or 'dialogue'")

    cfg = get_relay_audio_config()
    relay_url = (url or cfg.get("url") or "").rstrip("/")
    relay_token = token or cfg.get("token")

    if not relay_url or not relay_token:
        raise ValueError("RELAY_AUDIO_URL and RELAY_AUDIO_TOKEN must be configured")

    payload = {
        "text": text,
        "dialogue": dialogue,
        "voice_id": voice_id,
        "model_id": model_id,
        "caption": caption,
    }

    resp = requests.post(
        f"{relay_url}/audio",
        headers={"X-Relay-Token": relay_token},
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.text
