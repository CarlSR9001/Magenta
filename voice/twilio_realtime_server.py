import asyncio
import base64
import json
import time
import audioop
from typing import Optional

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import Response

import logging

from voice.letta_bridge import ask_letta
from voice.realtime_client import RealtimeClient
from voice.tts_client import stream_tts
from voice.voice_config import load_voice_config


app = FastAPI()
_cfg = load_voice_config()
logger = logging.getLogger("twilio_voice")
logging.basicConfig(level=logging.INFO)


def _get(cfg, path, default=None):
    cur = cfg
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
    return cur if cur is not None else default


@app.post(_get(_cfg, ["twilio", "voice_webhook_path"], "/twilio/voice"))
async def twilio_voice(_: Request):
    public_base = _get(_cfg, ["twilio", "public_base_url"], "").rstrip("/")
    stream_path = _get(_cfg, ["twilio", "stream_path"], "/twilio/stream")
    if not public_base:
        return Response(
            content="<Response><Say>Voice bridge not configured.</Say></Response>",
            media_type="text/xml",
        )
    if public_base.startswith("https://"):
        public_base = "wss://" + public_base[len("https://"):]
    if public_base.startswith("http://"):
        public_base = "ws://" + public_base[len("http://"):]
    ws_url = f"{public_base}{stream_path}"
    twiml = f"""<Response>
  <Connect>
    <Stream url=\"{ws_url}\" />
  </Connect>
</Response>"""
    return Response(content=twiml, media_type="text/xml")


@app.websocket(_get(_cfg, ["twilio", "stream_path"], "/twilio/stream"))
async def twilio_stream(ws: WebSocket):
    await ws.accept()

    model = _get(_cfg, ["realtime", "model"], "gpt-realtime-mini")
    voice = _get(_cfg, ["realtime", "voice"], "shimmer")
    turn_detection = _get(_cfg, ["realtime", "turn_detection"], {"type": "semantic_vad"})
    transcription_model = _get(_cfg, ["realtime", "transcription_model"], "gpt-4o-mini-transcribe")
    api_base = _get(_cfg, ["openai", "api_base"], "wss://api.openai.com/v1/realtime")

    tts_model = _get(_cfg, ["tts", "model"], "gpt-4o-mini-tts")
    tts_voice = _get(_cfg, ["tts", "voice"]) or voice
    tts_instructions = _get(_cfg, ["tts", "instructions"]) or "Speak naturally and conversationally."

    transcript_q: asyncio.Queue[str] = asyncio.Queue()

    async def _on_transcript(text: str):
        logger.info("Transcript: %s", text)
        await transcript_q.put(text)

    # Transcription: accept raw g711_ulaw from Twilio (8 kHz µ-law) directly
    transcription = RealtimeClient(
        mode="transcription",
        model=model,
        voice=voice,
        instructions="",
        turn_detection=turn_detection,
        input_format="g711_ulaw",
        output_format="g711_ulaw",
        transcription_model=transcription_model,
        api_base=api_base,
    )

    await transcription.connect(on_transcript=_on_transcript)

    stream_sid: Optional[str] = None
    mark_counter = 0

    async def _send_tts_to_twilio(text: str):
        """Synthesise *text* and send the resulting µ-law audio to Twilio."""
        nonlocal mark_counter

        async def _on_tts_chunk(pcm24k: bytes):
            nonlocal mark_counter
            # 24 kHz mono PCM -> 8 kHz mono PCM -> µ-law
            pcm8k, _ = audioop.ratecv(pcm24k, 2, 1, 24000, 8000, None)
            mulaw = audioop.lin2ulaw(pcm8k, 2)
            payload_b64 = base64.b64encode(mulaw).decode("ascii")
            msg: dict = {"event": "media", "media": {"payload": payload_b64}}
            if stream_sid:
                msg["streamSid"] = stream_sid
            await ws.send_text(json.dumps(msg))

        await stream_tts(
            text,
            voice=tts_voice,
            model=tts_model,
            instructions=tts_instructions,
            on_chunk=_on_tts_chunk,
        )

        # Send a mark so Twilio tells us when playback finishes
        mark_counter += 1
        mark_msg: dict = {"event": "mark", "mark": {"name": f"tts-{mark_counter}"}}
        if stream_sid:
            mark_msg["streamSid"] = stream_sid
        await ws.send_text(json.dumps(mark_msg))

    async def _handle_transcripts():
        while True:
            transcript = await transcript_q.get()
            if not transcript.strip():
                continue
            response_text = await asyncio.to_thread(ask_letta, transcript, "Phone")
            if response_text:
                logger.info("Letta response: %s", response_text[:200])
                await _send_tts_to_twilio(response_text)

    last_audio_time = time.monotonic()
    audio_bytes = 0

    async def _commit_loop():
        nonlocal last_audio_time, audio_bytes
        while True:
            await asyncio.sleep(0.3)
            # Only commit after a silence gap -- never during active speech
            if audio_bytes >= 6400 and time.monotonic() - last_audio_time > 0.8:
                await transcription.commit_audio()
                audio_bytes = 0

    reply_task = asyncio.create_task(_handle_transcripts())
    commit_task = asyncio.create_task(_commit_loop())

    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)
            event = data.get("event")
            if event == "start":
                stream_sid = data.get("streamSid")
                logger.info("Twilio stream started: %s", stream_sid)
            elif event == "media":
                payload = data.get("media", {}).get("payload")
                if payload:
                    mulaw = base64.b64decode(payload)
                    last_audio_time = time.monotonic()
                    audio_bytes += len(mulaw)
                    # Send raw µ-law directly (input_format is g711_ulaw)
                    await transcription.send_audio(mulaw)
            elif event == "stop":
                break
    finally:
        reply_task.cancel()
        commit_task.cancel()
        await transcription.close()
