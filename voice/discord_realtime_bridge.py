import asyncio
import audioop
import os
import queue
import time
from typing import Optional
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import logging

import discord
from discord.ext import voice_recv

from voice.letta_bridge import ask_letta
from voice.realtime_client import RealtimeClient
from voice.tts_client import stream_tts
from voice.voice_config import load_voice_config


class RealtimeAudioOut(discord.AudioSource):
    def __init__(self, audio_q: "queue.Queue[bytes]") -> None:
        self._q = audio_q
        self._buffer = b""
        self._frame_bytes = 3840  # 20ms @ 48kHz stereo 16-bit

    def read(self) -> bytes:
        while len(self._buffer) < self._frame_bytes:
            try:
                chunk = self._q.get(timeout=1.0)
            except queue.Empty:
                chunk = b"\x00" * self._frame_bytes
            self._buffer += chunk
        out = self._buffer[: self._frame_bytes]
        self._buffer = self._buffer[self._frame_bytes :]
        return out

    def is_opus(self) -> bool:
        return False


class RealtimeSink(voice_recv.AudioSink):
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        transcription: RealtimeClient,
        logger: logging.Logger,
        last_audio_time_ref: dict,
    ) -> None:
        self._loop = loop
        self._transcription = transcription
        self._logger = logger
        self._frames = 0
        self._last_audio_time_ref = last_audio_time_ref

    def write(self, user, voice_data: voice_recv.VoiceData) -> None:
        pcm = getattr(voice_data, "pcm", None) or getattr(voice_data, "audio", None)
        if not pcm:
            return
        self._frames += 1
        if self._frames == 1:
            self._logger.info("Received first audio frame from Discord")
        # 48 kHz stereo -> mono -> 24 kHz mono (pcm16 requires 24 kHz)
        mono = audioop.tomono(pcm, 2, 0.5, 0.5)
        pcm24k, _ = audioop.ratecv(mono, 2, 1, 48000, 24000, None)
        self._last_audio_time_ref["t"] = time.monotonic()
        self._last_audio_time_ref["frames"] += 1
        self._last_audio_time_ref["bytes"] += len(pcm24k)
        asyncio.run_coroutine_threadsafe(self._transcription.send_audio(pcm24k), self._loop)

    def wants_opus(self) -> bool:
        return False

    def cleanup(self) -> None:
        return


def _pcm24k_to_discord(pcm24k: bytes) -> bytes:
    """Convert 24 kHz mono PCM to 48 kHz stereo PCM for Discord playback."""
    pcm48k, _ = audioop.ratecv(pcm24k, 2, 1, 24000, 48000, None)
    stereo = audioop.tostereo(pcm48k, 2, 1.0, 1.0)
    return stereo


async def main() -> None:
    cfg = load_voice_config()
    guild_id = int(cfg.get("discord_voice", {}).get("guild_id", "0") or 0)
    channel_id = int(cfg.get("discord_voice", {}).get("channel_id", "0") or 0)
    if not guild_id or not channel_id:
        raise RuntimeError("discord_voice.guild_id and discord_voice.channel_id must be set")
    api_port = int(cfg.get("discord_voice", {}).get("api_port", 8791) or 8791)
    api_token = cfg.get("discord_voice", {}).get("api_token", "") or os.getenv("DISCORD_VOICE_BRIDGE_TOKEN", "")

    model = cfg.get("realtime", {}).get("model", "gpt-realtime-mini")
    voice = cfg.get("realtime", {}).get("voice", "shimmer")
    instructions = cfg.get("realtime", {}).get("instructions", "")
    turn_detection = cfg.get("realtime", {}).get("turn_detection", {"type": "semantic_vad"})
    transcription_model = cfg.get("realtime", {}).get("transcription_model", "gpt-4o-mini-transcribe")
    api_base = cfg.get("openai", {}).get("api_base", "wss://api.openai.com/v1/realtime")

    tts_model = cfg.get("tts", {}).get("model", "gpt-4o-mini-tts")
    tts_voice = cfg.get("tts", {}).get("voice") or voice
    tts_instructions = cfg.get("tts", {}).get("instructions") or "Speak naturally and conversationally."

    loop = asyncio.get_running_loop()
    out_q: "queue.Queue[bytes]" = queue.Queue(maxsize=200)
    transcript_q: asyncio.Queue[str] = asyncio.Queue()
    last_audio_state = {"t": time.monotonic(), "frames": 0, "bytes": 0}
    speaking_state = {"until": 0.0}

    async def _enqueue_discord_audio(pcm24k_chunk: bytes) -> None:
        """Callback for TTS: resample 24 kHz mono -> 48 kHz stereo and queue."""
        stereo = _pcm24k_to_discord(pcm24k_chunk)
        try:
            out_q.put_nowait(stereo)
        except queue.Full:
            pass

    async def _on_transcript(text: str) -> None:
        logger.info("Transcript: %s", text)
        await transcript_q.put(text)

    # Transcription only -- TTS is handled by the REST API
    transcription = RealtimeClient(
        mode="transcription",
        model=model,
        voice=voice,
        instructions="",
        turn_detection=turn_detection,
        input_format="pcm16",
        output_format="pcm16",
        transcription_model=transcription_model,
        api_base=api_base,
    )

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("discord_voice")

    if not discord.opus.is_loaded():
        try:
            discord.opus.load_opus("libopus.so.0")
            logger.info("Loaded opus library")
        except Exception as e:
            logger.error("Failed to load opus library: %s", e)

    intents = discord.Intents.none()
    intents.guilds = True
    intents.voice_states = True
    client = discord.Client(intents=intents)
    control_server = {"server": None}

    async def _speak(text: str) -> None:
        """Synthesise *text* via TTS and queue audio for Discord playback."""
        # Clear stale audio before speaking
        try:
            while True:
                out_q.get_nowait()
        except queue.Empty:
            pass

        words = len(text.split())
        duration = max(2.0, words / 2.5)
        speaking_state["until"] = time.monotonic() + duration

        await stream_tts(
            text,
            voice=tts_voice,
            model=tts_model,
            instructions=tts_instructions,
            on_chunk=_enqueue_discord_audio,
        )

    def start_control_server(loop: asyncio.AbstractEventLoop) -> None:
        class Handler(BaseHTTPRequestHandler):
            def _send(self, code: int, payload: dict) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:  # noqa: N802
                if self.path not in {"/say", "/discord/say"}:
                    self._send(404, {"error": "not found"})
                    return
                if api_token:
                    auth = self.headers.get("Authorization", "")
                    if auth != f"Bearer {api_token}":
                        self._send(401, {"error": "unauthorized"})
                        return
                length = int(self.headers.get("Content-Length", "0") or 0)
                raw = self.rfile.read(length)
                try:
                    data = json.loads(raw.decode("utf-8"))
                except Exception:
                    self._send(400, {"error": "invalid json"})
                    return
                text = (data.get("text") or "").strip()
                if not text:
                    self._send(400, {"error": "text required"})
                    return
                asyncio.run_coroutine_threadsafe(_speak(text), loop)
                self._send(200, {"status": "ok"})

            def log_message(self, format, *args):  # noqa: A002
                return

        server = HTTPServer(("127.0.0.1", api_port), Handler)
        control_server["server"] = server
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        logger.info("Discord voice control server listening on 127.0.0.1:%s", api_port)

    async def _handle_transcripts():
        buffer = []
        while True:
            try:
                transcript = await asyncio.wait_for(transcript_q.get(), timeout=1.2)
                if transcript.strip():
                    buffer.append(transcript.strip())
            except asyncio.TimeoutError:
                if not buffer:
                    continue
                merged = " ".join(buffer).strip()
                buffer.clear()
                if time.monotonic() < speaking_state["until"]:
                    continue
                response_text = await asyncio.to_thread(ask_letta, merged, "Discord Voice")
                logger.info("Letta reply length: %s", len(response_text or ""))
                if response_text:
                    await _speak(response_text)

    async def _commit_loop():
        while True:
            await asyncio.sleep(0.3)
            elapsed = time.monotonic() - last_audio_state["t"]
            # Only commit after a silence gap (elapsed > 0.8).  Never
            # commit on a fixed timer during active speech -- that was
            # splitting early audio into a tiny buffer the VAD discarded.
            if last_audio_state["bytes"] >= 6400 and elapsed > 0.8:
                await transcription.commit_audio()
                last_audio_state["frames"] = 0
                last_audio_state["bytes"] = 0

    @client.event
    async def on_ready():
        logger.info("Discord bot ready: %s", client.user)
        await transcription.connect(on_transcript=_on_transcript)
        start_control_server(loop)

        guild = client.get_guild(guild_id)
        if not guild:
            raise RuntimeError(f"Guild {guild_id} not found")
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.VoiceChannel):
            raise RuntimeError(f"Channel {channel_id} is not a voice channel")

        vc: Optional[discord.VoiceClient] = await channel.connect(
            cls=voice_recv.VoiceRecvClient,
            self_deaf=False,
            self_mute=False,
        )
        if vc is None:
            raise RuntimeError("Failed to connect to voice channel")

        logger.info("Connected to voice channel %s", channel_id)
        sink = RealtimeSink(loop, transcription, logger, last_audio_state)
        vc.listen(sink)

        audio_source = RealtimeAudioOut(out_q)
        vc.play(audio_source)

        asyncio.create_task(_handle_transcripts())
        asyncio.create_task(_commit_loop())

    token = os.getenv("DISCORD_BOT_TOKEN", "")
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN must be set")
    await client.start(token)


if __name__ == "__main__":
    asyncio.run(main())
