"""Discord voice tools for Magenta.

Basic: join a voice channel and play a short ElevenLabs TTS clip.
"""

from pydantic import BaseModel, Field


class DiscordVoiceSpeakArgs(BaseModel):
    guild_id: str = Field(..., description="Discord guild/server ID")
    channel_id: str = Field(..., description="Voice channel ID to join")
    text: str = Field(..., description="Text to speak")
    voice_id: str = Field(default="", description="Optional ElevenLabs voice ID override")


def discord_voice_speak(guild_id: str, channel_id: str, text: str, voice_id: str = "") -> str:
    """Join a Discord voice channel and speak a short TTS message.

    Requires DISCORD_BOT_TOKEN in env and ffmpeg on system.
    Note: This is a one-shot connection for a single utterance.
    """
    import os
    import json
    import asyncio
    import tempfile
    from pathlib import Path
    from urllib import request as urlrequest

    bridge_url = os.getenv("DISCORD_VOICE_BRIDGE_URL", "").strip()
    bridge_token = os.getenv("DISCORD_VOICE_BRIDGE_TOKEN", "").strip()
    if bridge_url:
        payload = json.dumps({"text": text}).encode("utf-8")
        req = urlrequest.Request(bridge_url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        if bridge_token:
            req.add_header("Authorization", f"Bearer {bridge_token}")
        try:
            with urlrequest.urlopen(req, timeout=15) as resp:
                body = resp.read().decode("utf-8")
            return body or json.dumps({"status": "ok"})
        except Exception as e:
            return json.dumps({"error": "bridge request failed", "details": str(e)})

    try:
        import discord
    except Exception as e:
        return json.dumps({"error": "discord.py not available", "details": str(e)})

    from clients.elevenlabs import text_to_speech

    token = os.getenv("DISCORD_BOT_TOKEN", "")
    if not token:
        return json.dumps({"error": "DISCORD_BOT_TOKEN must be set"})
    if not text.strip():
        return json.dumps({"error": "Text must be non-empty"})

    async def _run():
        intents = discord.Intents.none()
        intents.guilds = True
        client = discord.Client(intents=intents)

        result = {"status": "error"}

        async def _speak():
            nonlocal result
            guild = client.get_guild(int(guild_id))
            if not guild:
                result = {"error": f"Guild {guild_id} not found"}
                await client.close()
                return
            channel = guild.get_channel(int(channel_id))
            if not channel or not isinstance(channel, discord.VoiceChannel):
                result = {"error": f"Voice channel {channel_id} not found"}
                await client.close()
                return

            vc = await channel.connect()
            try:
                audio = text_to_speech(text=text, voice_id=voice_id or None)
                with tempfile.TemporaryDirectory() as td:
                    mp3_path = Path(td) / "tts.mp3"
                    mp3_path.write_bytes(audio)
                    source = discord.FFmpegPCMAudio(str(mp3_path))
                    vc.play(source)
                    while vc.is_playing():
                        await asyncio.sleep(0.2)
                result = {"status": "ok"}
            finally:
                await vc.disconnect()
                await client.close()

        @client.event
        async def on_ready():
            await _speak()

        await client.start(token)
        return result

    try:
        output = asyncio.run(_run())
        return json.dumps(output)
    except Exception as e:
        return json.dumps({"error": str(e)})
