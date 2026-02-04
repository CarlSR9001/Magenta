"""Discord tools for Magenta.

These tools provide read/write access to Discord.
"""

from pydantic import BaseModel, Field


class ListDiscordMessagesArgs(BaseModel):
    channel_id: str = Field(..., description="Discord channel ID to read from")
    limit: int = Field(default=10, ge=1, le=50, description="Number of messages to fetch")


def discord_list_messages(channel_id: str, limit: int = 10) -> str:
    """List recent messages from a Discord channel.

    Args:
        channel_id: The Discord channel ID to read from.
        limit: Number of messages to fetch (1-50, default 10).

    Returns:
        YAML-formatted list of messages.
    """
    import os
    import requests
    import yaml

    bot_token = os.getenv("DISCORD_BOT_TOKEN")
    if not bot_token:
        return "Error: DISCORD_BOT_TOKEN must be set"

    try:
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
        headers = {
            "Authorization": f"Bot {bot_token}",
            "Content-Type": "application/json",
        }
        resp = requests.get(url, headers=headers, params={"limit": limit}, timeout=10)
        resp.raise_for_status()

        messages = resp.json()
        formatted = []
        for msg in messages:
            formatted.append({
                "id": msg.get("id"),
                "author": msg.get("author", {}).get("username", "unknown"),
                "author_id": msg.get("author", {}).get("id"),
                "content": msg.get("content", ""),
                "timestamp": msg.get("timestamp"),
                "referenced_message_id": msg.get("referenced_message", {}).get("id") if msg.get("referenced_message") else None,
            })

        return yaml.dump(formatted, default_flow_style=False, sort_keys=False, allow_unicode=True)
    except Exception as e:
        return f"Error: {e}"


class SendDiscordMessageArgs(BaseModel):
    channel_id: str = Field(..., description="Discord channel ID to send to")
    content: str = Field(..., description="Message content (max 2000 chars)")
    reply_to: str = Field(default="", description="Message ID to reply to (optional)")


def discord_send_message(channel_id: str, content: str, reply_to: str = "") -> str:
    """Send a message to a Discord channel.

    Args:
        channel_id: The Discord channel ID to send to.
        content: Message content (max 2000 characters).
        reply_to: Optional message ID to reply to.

    Returns:
        Success message with message URL or error.
    """
    import os
    import requests

    bot_token = os.getenv("DISCORD_BOT_TOKEN")
    if not bot_token:
        return "Error: DISCORD_BOT_TOKEN must be set"

    if len(content) > 2000:
        return f"Error: Message exceeds 2000 chars ({len(content)})"

    try:
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
        headers = {
            "Authorization": f"Bot {bot_token}",
            "Content-Type": "application/json",
        }
        payload = {"content": content}
        if reply_to:
            payload["message_reference"] = {"message_id": reply_to}

        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        resp.raise_for_status()

        msg = resp.json()
        msg_id = msg.get("id")
        guild_id = msg.get("guild_id", "@me")
        return f"Message sent! URL: https://discord.com/channels/{guild_id}/{channel_id}/{msg_id}"
    except Exception as e:
        return f"Error: {e}"


class GetDiscordChannelArgs(BaseModel):
    channel_id: str = Field(..., description="Discord channel ID")


def discord_get_channel(channel_id: str) -> str:
    """Get information about a Discord channel.

    Args:
        channel_id: The Discord channel ID.

    Returns:
        Channel information as YAML.
    """
    import os
    import requests
    import yaml

    bot_token = os.getenv("DISCORD_BOT_TOKEN")
    if not bot_token:
        return "Error: DISCORD_BOT_TOKEN must be set"

    try:
        url = f"https://discord.com/api/v10/channels/{channel_id}"
        headers = {
            "Authorization": f"Bot {bot_token}",
            "Content-Type": "application/json",
        }
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()

        channel = resp.json()
        info = {
            "id": channel.get("id"),
            "name": channel.get("name"),
            "type": channel.get("type"),
            "guild_id": channel.get("guild_id"),
            "topic": channel.get("topic"),
        }
        return yaml.dump(info, default_flow_style=False, sort_keys=False, allow_unicode=True)
    except Exception as e:
        return f"Error: {e}"


class AddDiscordReactionArgs(BaseModel):
    channel_id: str = Field(..., description="Discord channel ID")
    message_id: str = Field(..., description="Message ID to react to")
    emoji: str = Field(..., description="Emoji to react with (e.g., '👍' or 'custom_emoji:123456')")


def discord_add_reaction(channel_id: str, message_id: str, emoji: str) -> str:
    """Add a reaction to a Discord message.

    Args:
        channel_id: The Discord channel ID.
        message_id: The message ID to react to.
        emoji: The emoji to use (unicode or custom format).

    Returns:
        Success or error message.
    """
    import os
    import requests
    from urllib.parse import quote

    bot_token = os.getenv("DISCORD_BOT_TOKEN")
    if not bot_token:
        return "Error: DISCORD_BOT_TOKEN must be set"

    try:
        encoded_emoji = quote(emoji, safe='')
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}/reactions/{encoded_emoji}/@me"
        headers = {
            "Authorization": f"Bot {bot_token}",
        }
        resp = requests.put(url, headers=headers, timeout=10)
        resp.raise_for_status()

        return f"Reaction '{emoji}' added to message {message_id}"
    except Exception as e:
        return f"Error: {e}"


class GetDiscordUserArgs(BaseModel):
    user_id: str = Field(..., description="Discord user ID")


def discord_get_user(user_id: str) -> str:
    """Get information about a Discord user.

    Args:
        user_id: The Discord user ID.

    Returns:
        User information as YAML.
    """
    import os
    import requests
    import yaml

    bot_token = os.getenv("DISCORD_BOT_TOKEN")
    if not bot_token:
        return "Error: DISCORD_BOT_TOKEN must be set"

    try:
        url = f"https://discord.com/api/v10/users/{user_id}"
        headers = {
            "Authorization": f"Bot {bot_token}",
            "Content-Type": "application/json",
        }
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()

        user = resp.json()
        info = {
            "id": user.get("id"),
            "username": user.get("username"),
            "display_name": user.get("global_name") or user.get("username"),
            "bot": user.get("bot", False),
            "avatar": user.get("avatar"),
        }
        return yaml.dump(info, default_flow_style=False, sort_keys=False, allow_unicode=True)
    except Exception as e:
        return f"Error: {e}"
