import asyncio
import base64
import json
import os
from typing import Any, Awaitable, Callable, Dict, Optional

import logging

import websockets


class RealtimeClient:
    """OpenAI Realtime API WebSocket client for audio transcription.

    Connects to the Realtime API, streams audio in, and receives
    transcripts via the on_transcript callback.  Handles both the
    beta (``realtime=v1``) and GA event naming conventions so the
    same code works regardless of API version.
    """

    def __init__(
        self,
        mode: str,
        model: str,
        voice: str,
        instructions: str,
        turn_detection: Dict[str, Any],
        input_format: str,
        output_format: str,
        transcription_model: str,
        api_base: str,
        api_key: Optional[str] = None,
    ) -> None:
        self.mode = mode
        self.model = model
        self.voice = voice
        self.instructions = instructions
        self.turn_detection = turn_detection
        self.input_format = input_format
        self.output_format = output_format
        self.transcription_model = transcription_model
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._recv_task: Optional[asyncio.Task] = None
        self._on_audio: Optional[Callable[[bytes], Awaitable[None]]] = None
        self._on_transcript: Optional[Callable[[str], Awaitable[None]]] = None
        self._closed = False
        self._logger = logging.getLogger(f"realtime.{self.mode}")

    async def connect(
        self,
        on_audio: Optional[Callable[[bytes], Awaitable[None]]] = None,
        on_transcript: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> None:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY must be set")

        url = f"{self.api_base}?model={self.model}"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "OpenAI-Beta": "realtime=v1",
        }
        self._ws = await websockets.connect(url, extra_headers=headers, max_queue=32)
        self._on_audio = on_audio
        self._on_transcript = on_transcript

        if self.mode == "transcription":
            await self._send(
                {
                    "type": "session.update",
                    "session": {
                        "input_audio_format": self.input_format,
                        "input_audio_transcription": {
                            "model": self.transcription_model,
                        },
                        "turn_detection": self.turn_detection,
                    },
                }
            )
        else:
            await self._send(
                {
                    "type": "session.update",
                    "session": {
                        "voice": self.voice,
                        "instructions": self.instructions,
                        "turn_detection": self.turn_detection,
                        "input_audio_format": self.input_format,
                        "output_audio_format": self.output_format,
                    },
                }
            )

        self._recv_task = asyncio.create_task(self._recv_loop())

    async def close(self) -> None:
        self._closed = True
        if self._ws is not None:
            await self._ws.close()
        if self._recv_task is not None:
            self._recv_task.cancel()

    async def send_audio(self, payload: bytes) -> None:
        if not self._ws:
            return
        audio_b64 = base64.b64encode(payload).decode("ascii")
        await self._send({"type": "input_audio_buffer.append", "audio": audio_b64})

    async def commit_audio(self) -> None:
        if not self._ws:
            return
        await self._send({"type": "input_audio_buffer.commit"})

    async def _send(self, payload: Dict[str, Any]) -> None:
        if not self._ws:
            return
        await self._ws.send(json.dumps(payload))

    # -- event names for both beta and GA APIs --------------------------
    _AUDIO_DELTA_EVENTS = {
        "response.audio.delta",           # beta
        "response.output_audio.delta",    # GA
    }
    _TRANSCRIPT_EVENTS = {
        "conversation.item.input_audio_transcription.completed",  # beta + GA
    }

    async def _recv_loop(self) -> None:
        assert self._ws is not None
        while not self._closed:
            try:
                raw = await self._ws.recv()
            except websockets.ConnectionClosed:
                self._logger.warning("Realtime WebSocket closed")
                break
            data = json.loads(raw)
            msg_type = data.get("type")

            if msg_type in self._AUDIO_DELTA_EVENTS:
                audio_b64 = data.get("delta", "")
                if audio_b64 and self._on_audio:
                    audio = base64.b64decode(audio_b64)
                    await self._on_audio(audio)
                continue

            if msg_type in self._TRANSCRIPT_EVENTS:
                transcript = data.get("transcript", "")
                if transcript and self._on_transcript:
                    await self._on_transcript(transcript)
                continue

            if msg_type and "input_audio_transcription" in msg_type:
                transcript = data.get("transcript", "")
                if transcript and self._on_transcript:
                    await self._on_transcript(transcript)
                continue

            if msg_type == "error":
                self._logger.error("Realtime error: %s", data)
                continue
