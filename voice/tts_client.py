"""Streaming TTS via OpenAI REST API.

Sends text to /v1/audio/speech and yields PCM 24 kHz 16-bit mono chunks
suitable for real-time playback after resampling.
"""

import asyncio
import os
import logging
from typing import Awaitable, Callable, Optional

import requests

logger = logging.getLogger(__name__)

# 100 ms of audio at 24 kHz 16-bit mono = 24000 * 2 / 10 = 4800 bytes
_CHUNK_BYTES = 4800


async def stream_tts(
    text: str,
    voice: str = "shimmer",
    model: str = "gpt-4o-mini-tts",
    instructions: Optional[str] = None,
    api_key: Optional[str] = None,
    on_chunk: Optional[Callable[[bytes], Awaitable[None]]] = None,
) -> bytes:
    """Stream TTS audio, calling *on_chunk(pcm_bytes)* for each chunk.

    Returns the complete PCM buffer.  All audio is 24 kHz 16-bit mono PCM.
    """
    key = api_key or os.getenv("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError("OPENAI_API_KEY must be set")

    body: dict = {
        "model": model,
        "input": text,
        "voice": voice,
        "response_format": "pcm",
    }
    if instructions and model not in ("tts-1", "tts-1-hd"):
        body["instructions"] = instructions

    def _do_stream() -> list[bytes]:
        resp = requests.post(
            "https://api.openai.com/v1/audio/speech",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json=body,
            stream=True,
            timeout=30,
        )
        resp.raise_for_status()
        return list(resp.iter_content(chunk_size=_CHUNK_BYTES))

    chunks = await asyncio.to_thread(_do_stream)

    full_pcm = b""
    for chunk in chunks:
        full_pcm += chunk
        if on_chunk:
            await on_chunk(chunk)

    logger.info("TTS streamed %d bytes for %d chars of text", len(full_pcm), len(text))
    return full_pcm
