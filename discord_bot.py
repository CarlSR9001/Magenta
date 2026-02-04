#!/usr/bin/env python3
"""Discord bot for Magenta.

Listens for messages and mentions, routes them to Magenta via Letta.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import Message, Intents

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config_loader import get_discord_config, get_letta_config
from letta_client import Letta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


class MagentaDiscordBot(discord.Client):
    """Discord bot that routes messages to Magenta."""

    def __init__(self, letta_client: Letta, agent_id: str, **kwargs):
        # Set up intents
        intents = Intents.default()
        intents.message_content = True
        intents.dm_messages = True
        intents.guild_messages = True

        super().__init__(intents=intents, **kwargs)

        self.letta = letta_client
        self.agent_id = agent_id
        self.config = get_discord_config()

        # Track channels we're actively conversing in
        # Values include last activity time and the author who triggered it to reduce cross-talk.
        self.active_channels: dict[str, dict[str, str | datetime]] = {}

        # Rate limiting: per-user message timestamps
        self._user_messages: dict[str, list[datetime]] = defaultdict(list)
        self._rate_limit_max = 3        # max messages per window
        self._rate_limit_window = 30    # window in seconds
        # Lock to prevent concurrent Letta calls
        self._processing_lock = asyncio.Lock()

    @staticmethod
    def _soft_mentioned(message: Message) -> bool:
        """Heuristic: detect when someone is likely talking to Magenta by name."""
        content = (message.content or "").strip()
        if not content:
            return False

        text = content.lower()
        if not re.search(r"\bmagenta\b", text):
            return False

        # Direct address patterns (human-like cues)
        direct_address = bool(
            re.search(r"^(hey|hi|yo|ok|okay|pls|please)?\s*magenta\b", text)
            or re.search(r"\bmagenta\b[,:;!\?]", text)
        )

        has_question = "?" in text
        has_second_person = bool(re.search(r"\b(you|your|yours)\b", text))
        has_request = bool(re.search(r"\b(can you|could you|would you|please|pls)\b", text))

        # Avoid third-person statements unless other cues exist
        third_person = bool(re.search(r"\bmagenta\b\s+(is|was|seems|sounds|feels)\b", text))

        if direct_address:
            return True
        if has_question or has_request or has_second_person:
            return True
        if third_person:
            return False

        # Default to no if only name is present with no cues
        return False

    async def on_ready(self):
        """Called when the bot is ready."""
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guild(s)")
        for guild in self.guilds:
            logger.info(f"  - {guild.name} (ID: {guild.id})")

    async def on_message(self, message: Message):
        """Handle incoming messages."""
        # Ignore our own messages
        if message.author == self.user:
            return

        # Ignore bots (optional - can be configured)
        if message.author.bot:
            return

        # Check if this is a DM
        is_dm = isinstance(message.channel, discord.DMChannel)

        # Check if we're mentioned
        is_mentioned = self.user.mentioned_in(message)
        is_soft_mentioned = False
        if self.config.get("respond_to_mentions", True):
            is_soft_mentioned = self._soft_mentioned(message)

        # Check if this is a reply to one of our messages
        is_reply_to_us = False
        ref_msg = None
        if message.reference and message.reference.message_id:
            try:
                ref_msg = await message.channel.fetch_message(message.reference.message_id)
                is_reply_to_us = ref_msg.author == self.user
            except Exception:
                pass

        # Check if this channel has recent activity with us
        channel_id = str(message.channel.id)
        active_entry = self.active_channels.get(channel_id)
        is_active_channel = active_entry is not None

        # Decide whether to respond
        should_respond = False

        if is_dm and self.config.get("respond_to_dms", True):
            should_respond = True
        elif is_mentioned and self.config.get("respond_to_mentions", True):
            should_respond = True
        elif is_soft_mentioned:
            should_respond = True
        elif is_reply_to_us:
            should_respond = True
        elif is_active_channel:
            # Check if channel activity is recent (within 5 minutes)
            last_activity = active_entry.get("last_activity") if active_entry else None
            last_author_id = active_entry.get("last_author_id") if active_entry else None
            if last_activity and (datetime.now(timezone.utc) - last_activity).total_seconds() < 300:
                # Only continue the "active" thread with the same author to reduce cross-talk
                if last_author_id == str(message.author.id):
                    should_respond = True

        # Check allowed channels if configured
        allowed_channels = self.config.get("allowed_channels", [])
        if allowed_channels and not is_dm:
            if channel_id not in allowed_channels and str(message.channel.id) not in allowed_channels:
                should_respond = False
        # Check allowed guilds if configured
        allowed_guilds = self.config.get("guild_ids", [])
        if allowed_guilds and not is_dm:
            guild_id = str(message.guild.id) if message.guild else ""
            if guild_id not in allowed_guilds:
                should_respond = False

        if not should_respond:
            return

        # Rate limit check per user
        user_id = str(message.author.id)
        now = datetime.now(timezone.utc)
        # Prune old timestamps
        self._user_messages[user_id] = [
            t for t in self._user_messages[user_id]
            if (now - t).total_seconds() < self._rate_limit_window
        ]
        if len(self._user_messages[user_id]) >= self._rate_limit_max:
            logger.warning(f"Rate limited user {message.author.name} ({user_id})")
            return
        self._user_messages[user_id].append(now)

        # Build context for Magenta
        await self.respond_to_message(message, is_dm=is_dm)

    async def respond_to_message(self, message: Message, is_dm: bool = False):
        """Send message to Magenta and reply with response."""
        channel_id = str(message.channel.id)

        # Build the prompt for Magenta
        author_name = message.author.display_name or message.author.name
        author_id = str(message.author.id)

        # Get server/channel names for context
        server_name = ""
        channel_name = ""
        server_id = ""
        if not is_dm and hasattr(message.channel, 'guild') and message.channel.guild:
            server_name = message.channel.guild.name
            channel_name = getattr(message.channel, 'name', '')
            server_id = str(message.channel.guild.id)

        # Get recent context from the channel
        context_messages = []
        try:
            async for msg in message.channel.history(limit=5, before=message):
                who = "Magenta (you)" if msg.author == self.user else f"{msg.author.display_name}"
                who_id = str(msg.author.id)
                context_messages.insert(0, f"  [{who} ({who_id})]: {msg.content[:200]}")
        except Exception:
            pass

        context_str = "\n".join(context_messages[-3:]) if context_messages else "  (no recent messages)"

        location = f"DM with {author_name}" if is_dm else f"#{channel_name} in {server_name}"
        channel_line = f"Channel ID: {channel_id}"
        server_line = f"Server ID: {server_id}" if server_id else ""

        reply_context = "  (not a reply)"
        ref_msg = None
        if message.reference and message.reference.message_id:
            try:
                ref_msg = await message.channel.fetch_message(message.reference.message_id)
            except Exception:
                ref_msg = None
        if ref_msg:
            ref_author = ref_msg.author.display_name or ref_msg.author.name
            ref_author_id = str(ref_msg.author.id)
            reply_context = f"  [{ref_author} ({ref_author_id})]: {ref_msg.content[:200]}"

        prompt = f"""[DISCORD] {location}
{server_line}
{channel_line}

{author_name} ({author_id}) says:
> {message.content}

Replying to:
{reply_context}

Recent channel history:
{context_str}

---
This is a Discord message (NOT Bluesky, NOT Moltbook, NOT your operator's main window).
Treat each Discord server as isolated. Do NOT reference or reuse info from other servers.
Reply using discord_send_message with channel_id="{channel_id}" and reply_to="{message.id}".
Keep it under 2000 characters."""

        try:
            # Serialize Letta calls - one at a time to prevent loops
            async with self._processing_lock:
              # Show typing indicator while processing
              async with message.channel.typing():
                # Send to Magenta via Letta
                response = await asyncio.to_thread(
                    self.letta.agents.messages.create,
                    agent_id=self.agent_id,
                    messages=[{"role": "user", "content": prompt}],
                )

                # Mark channel as active for this author to reduce cross-talk
                self.active_channels[channel_id] = {
                    "last_activity": datetime.now(timezone.utc),
                    "last_author_id": author_id,
                }

                # Check if Magenta used the discord_send_message tool
                # If not, send her text response directly
                tool_was_called = False
                assistant_text = None

                for msg in response.messages:
                    msg_type = type(msg).__name__

                    if msg_type == "ToolCallMessage":
                        # Check if it's a discord tool
                        if hasattr(msg, "tool_calls"):
                            for tc in msg.tool_calls:
                                tool_name = getattr(tc, "name", None)
                                if tool_name == "discord_send_message":
                                    tool_was_called = True
                                    break

                    elif msg_type == "AssistantMessage" and hasattr(msg, "content") and msg.content:
                        # Extract thinking tags and get clean response
                        content = msg.content
                        # Remove </think> tags and everything before them
                        while "</think>" in content:
                            idx = content.rfind("</think>")
                            content = content[idx + 8:].strip()
                        if content:
                            assistant_text = content

                # Only send to Discord if she explicitly used discord_send_message
                # Don't auto-send her internal monologue
                if not tool_was_called:
                    logger.info(f"No Discord tool called - response not sent to channel")

                logger.info(f"Processed Discord message from {author_name} in {channel_id}")

        except Exception as e:
            logger.error(f"Error processing Discord message: {e}")
            # Optionally send error reaction
            try:
                await message.add_reaction("⚠️")
            except Exception:
                pass

    async def cleanup_active_channels(self):
        """Periodically clean up stale active channel entries."""
        while True:
            await asyncio.sleep(300)  # Every 5 minutes
            now = datetime.now(timezone.utc)
            stale = []
            for ch_id, entry in self.active_channels.items():
                last_active = entry.get("last_activity")
                if not last_active:
                    stale.append(ch_id)
                elif (now - last_active).total_seconds() > 600:  # 10 minutes
                    stale.append(ch_id)
            for ch_id in stale:
                del self.active_channels[ch_id]
            if stale:
                logger.debug(f"Cleaned up {len(stale)} stale channel entries")


async def main():
    """Main entry point."""
    # Load configs
    discord_config = get_discord_config()
    letta_config = get_letta_config()

    bot_token = discord_config.get("bot_token")
    if not bot_token:
        logger.error("DISCORD_BOT_TOKEN not configured!")
        logger.error("Set it in config.yaml under discord.bot_token or as DISCORD_BOT_TOKEN env var")
        sys.exit(1)

    # Create Letta client
    client_params = {
        "api_key": letta_config["api_key"],
        "timeout": letta_config["timeout"],
    }
    if letta_config.get("base_url"):
        client_params["base_url"] = letta_config["base_url"]

    letta_client = Letta(**client_params)
    agent_id = letta_config["agent_id"]

    # Verify agent exists
    try:
        agent = letta_client.agents.retrieve(agent_id=agent_id)
        logger.info(f"Connected to Letta agent: {agent.name} ({agent_id})")
    except Exception as e:
        logger.error(f"Failed to connect to Letta agent {agent_id}: {e}")
        sys.exit(1)

    # Create and run bot
    bot = MagentaDiscordBot(letta_client=letta_client, agent_id=agent_id)

    # Start cleanup task
    async def run_bot():
        async with bot:
            bot.loop.create_task(bot.cleanup_active_channels())
            await bot.start(bot_token)

    await run_bot()


if __name__ == "__main__":
    asyncio.run(main())
