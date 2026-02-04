import logging
from typing import Optional

from clients.letta import get_letta_client, get_agent_id

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def ask_letta(text: str, caller_label: Optional[str] = None) -> str:
    client = get_letta_client()
    agent_id = get_agent_id()

    prompt = text.strip()
    if caller_label:
        prompt = f"[{caller_label}] {prompt}"
        if caller_label in {"Discord Voice", "Phone"}:
            prompt = (
                "You are speaking in a live voice conversation. "
                "Reply in 1-2 short sentences, no lists, no meta-talk, "
                "and do not mention missing tools or limitations. "
                "Speak naturally.\n"
                f"{prompt}"
            )

    last_assistant_msg = None
    try:
        for chunk in client.agents.messages.create_stream(
            agent_id=agent_id,
            messages=[{"role": "user", "content": prompt}],
        ):
            if getattr(chunk, "message_type", None) == "assistant_message":
                content = getattr(chunk, "content", "")
                if content:
                    last_assistant_msg = content
    except Exception:
        resp = client.agents.messages.create(
            agent_id=agent_id,
            messages=[{"role": "user", "content": prompt}],
        )
        for msg in getattr(resp, "messages", []):
            if getattr(msg, "message_type", None) == "assistant_message":
                content = getattr(msg, "content", "")
                if content:
                    last_assistant_msg = content
    if last_assistant_msg:
        logger.info("Letta response: %s", last_assistant_msg[:200])
    else:
        logger.warning("Letta returned no assistant message")
    return last_assistant_msg or ""
