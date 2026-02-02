#!/usr/bin/env python3
"""Magenta main loop - VPS orchestration for the Letta agent.

This is the Umbra-style main loop that:
1. Fetches notifications from Bluesky
2. Builds thread context
3. Sends prompts to the Letta agent
4. Handles tool call responses
"""

import logging
import json
import time
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

from letta_client import Letta
import requests

from config_loader import get_config, get_letta_config, get_bluesky_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


class BlueskyClient:
    """Simple Bluesky API client for reading."""
    
    def __init__(self, username: str, password: str, pds_uri: str = "https://bsky.social"):
        self.username = username
        self.password = password
        self.pds_uri = pds_uri.rstrip("/")
        self._session = None
    
    def _authenticate(self) -> Dict[str, Any]:
        """Get or refresh session."""
        if self._session:
            return self._session
        
        url = f"{self.pds_uri}/xrpc/com.atproto.server.createSession"
        resp = requests.post(url, json={"identifier": self.username, "password": self.password}, timeout=10)
        resp.raise_for_status()
        self._session = resp.json()
        return self._session
    
    def list_notifications(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Fetch recent notifications."""
        session = self._authenticate()
        url = f"{self.pds_uri}/xrpc/app.bsky.notification.listNotifications"
        headers = {"Authorization": f"Bearer {session['accessJwt']}"}
        resp = requests.get(url, headers=headers, params={"limit": limit}, timeout=15)
        resp.raise_for_status()
        return resp.json().get("notifications", [])
    
    def get_thread(self, uri: str, depth: int = 10) -> Dict[str, Any]:
        """Fetch thread context for a post."""
        session = self._authenticate()
        url = f"{self.pds_uri}/xrpc/app.bsky.feed.getPostThread"
        headers = {"Authorization": f"Bearer {session['accessJwt']}"}
        resp = requests.get(url, headers=headers, params={"uri": uri, "depth": depth}, timeout=15)
        resp.raise_for_status()
        return resp.json()


def flatten_thread(thread_data: Dict[str, Any]) -> str:
    """Convert thread data to readable text for the agent."""
    if not thread_data:
        return "(no thread data)"
    
    thread = thread_data.get("thread", {})
    posts = []
    
    def extract_post(node: Dict[str, Any], indent: int = 0):
        post = node.get("post", {})
        if not post:
            return
        
        author = post.get("author", {})
        handle = author.get("handle", "unknown")
        record = post.get("record", {})
        text = record.get("text", "")
        uri = post.get("uri", "")
        cid = post.get("cid", "")
        created = record.get("createdAt", "")
        
        prefix = "  " * indent
        posts.append(f"{prefix}@{handle}: {text}")
        posts.append(f"{prefix}  [uri: {uri}]")
        posts.append(f"{prefix}  [cid: {cid}]")
        
        # Process replies
        for reply in node.get("replies", []):
            extract_post(reply, indent + 1)
    
    # Process parent chain first
    parent = thread.get("parent")
    parent_chain = []
    while parent:
        parent_chain.append(parent)
        parent = parent.get("parent")
    
    for p in reversed(parent_chain):
        extract_post(p, 0)
    
    # Main post
    extract_post(thread, 0)
    
    return "\n".join(posts) if posts else "(empty thread)"


def build_notification_prompt(notification: Dict[str, Any], thread_context: str) -> str:
    """Build a prompt for the agent based on a notification."""
    reason = notification.get("reason", "unknown")
    author = notification.get("author", {})
    handle = author.get("handle", "unknown")
    uri = notification.get("uri", "")
    cid = notification.get("cid", "")
    
    record = notification.get("record", {})
    text = record.get("text", "(no text)")
    
    prompt = f"""You received a Bluesky notification:

TYPE: {reason}
FROM: @{handle}
TEXT: {text}

THREAD CONTEXT:
{thread_context}

POST DETAILS (for replying):
- parent_uri: {uri}
- parent_cid: {cid}

---

Decide how to respond:
1. If you want to reply, call bsky_publish_reply(text="your reply", parent_uri="{uri}", parent_cid="{cid}")
2. If you want to like, call bsky_like(uri="{uri}", cid="{cid}")
3. If you need to deliberate, call self_dialogue(initial_prompt="...", purpose="deliberation")
4. If no action needed, just acknowledge

Be thoughtful. Prefer restraint over action. If replying, keep it under 300 characters."""
    
    return prompt


def process_notification(
    client: Letta,
    agent_id: str,
    notification: Dict[str, Any],
    bsky: BlueskyClient,
    processed_uris: set
) -> bool:
    """Process a single notification."""
    uri = notification.get("uri", "")
    if uri in processed_uris:
        logger.debug(f"Skipping already processed: {uri}")
        return False
    
    reason = notification.get("reason", "")
    if reason not in {"mention", "reply"}:
        # Only process mentions and replies for now
        return False
    
    author = notification.get("author", {})
    handle = author.get("handle", "unknown")
    
    logger.info(f"Processing {reason} from @{handle}")
    
    # Fetch thread context
    try:
        thread_data = bsky.get_thread(uri, depth=10)
        thread_context = flatten_thread(thread_data)
    except Exception as e:
        logger.warning(f"Failed to get thread context: {e}")
        thread_context = "(could not fetch thread)"
    
    # Build and send prompt
    prompt = build_notification_prompt(notification, thread_context)
    
    try:
        response = client.agents.messages.create(
            agent_id=agent_id,
            messages=[{"role": "user", "content": prompt}]
        )
        
        # Log tool calls
        for msg in response.messages:
            if hasattr(msg, 'tool_call') and msg.tool_call:
                logger.info(f"  Tool called: {msg.tool_call.name}")
            if hasattr(msg, 'tool_return'):
                status = getattr(msg, 'status', 'unknown')
                logger.info(f"  Tool result: {status}")
        
        processed_uris.add(uri)
        return True
        
    except Exception as e:
        logger.error(f"Error sending to agent: {e}")
        return False


def run_loop(
    config_path: str = "config.yaml",
    interval_seconds: int = 180,
    jitter_seconds: int = 30,
    max_iterations: int = None
):
    """Main loop that processes notifications."""
    get_config(config_path)
    letta_cfg = get_letta_config()
    bsky_cfg = get_bluesky_config()
    
    # Initialize clients
    client = Letta(
        api_key=letta_cfg["api_key"],
        base_url=letta_cfg.get("base_url"),
        timeout=letta_cfg.get("timeout", 300)
    )
    agent_id = letta_cfg["agent_id"]
    
    bsky = BlueskyClient(
        username=bsky_cfg["username"],
        password=bsky_cfg["password"],
        pds_uri=bsky_cfg.get("pds_uri", "https://bsky.social")
    )
    
    # Track processed notifications
    from notification_db import NotificationDB
    db = NotificationDB()
    processed_uris = db.get_all_processed_uris()
    iteration = 0
    
    logger.info(f"Starting Magenta loop for agent {agent_id}")
    logger.info(f"Interval: {interval_seconds}s ± {jitter_seconds}s jitter")
    
    while max_iterations is None or iteration < max_iterations:
        iteration += 1
        logger.info(f"=== Iteration {iteration} ===")
        
        try:
            # Fetch notifications
            notifications = bsky.list_notifications(limit=20)
            logger.info(f"Fetched {len(notifications)} notifications")
            
            # Process new ones
            for notif in notifications:
                uri = notif.get("uri", "")
                if process_notification(client, agent_id, notif, bsky, processed_uris):
                    db.mark_processed(uri, status="processed", reason=notif.get("reason"), indexed_at=notif.get("indexedAt"))
            
        except Exception as e:
            logger.error(f"Error in loop: {e}")
        
        # Sleep with jitter
        sleep_time = interval_seconds + random.randint(-jitter_seconds, jitter_seconds)
        sleep_time = max(60, sleep_time)  # Minimum 60 seconds
        logger.info(f"Sleeping {sleep_time}s until next check")
        time.sleep(sleep_time)
    
    logger.info("Loop finished")


def run_once(config_path: str = "config.yaml"):
    """Run a single iteration (for testing)."""
    run_loop(config_path=config_path, max_iterations=1)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Magenta main loop")
    parser.add_argument("--config", default="config.yaml", help="Config file path")
    parser.add_argument("--interval", type=int, default=180, help="Check interval in seconds")
    parser.add_argument("--jitter", type=int, default=30, help="Jitter in seconds")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    
    args = parser.parse_args()
    
    if args.once:
        run_once(args.config)
    else:
        run_loop(
            config_path=args.config,
            interval_seconds=args.interval,
            jitter_seconds=args.jitter
        )
