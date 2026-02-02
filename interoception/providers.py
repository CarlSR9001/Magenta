"""External state providers for the interoception layer.

These providers give the limbic layer access to external state without
requiring it to do complex reasoning. The limbic layer asks simple questions
like "how many pending notifications?" and gets simple answers.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional
import json

from .limbic import ExternalStateProvider

logger = logging.getLogger(__name__)


class MagentaStateProvider(ExternalStateProvider):
    """State provider that integrates with Magenta's existing systems.

    This provider pulls state from:
    - Bluesky API (notifications)
    - Moltbook API (pending items)
    - Agent state store (action history)
    - Context management tools (usage)
    - Telemetry store (errors)
    """

    def __init__(
        self,
        agent_state_path: Optional[Path] = None,
        telemetry_path: Optional[Path] = None,
        bsky_api=None,
        letta_client=None,
        letta_agent_id: Optional[str] = None,
    ):
        self.agent_state_path = agent_state_path or Path("state/agent_state.json")
        self.telemetry_path = telemetry_path or Path("state/telemetry.jsonl")
        self._bsky_api = bsky_api
        self._letta_client = letta_client
        self._letta_agent_id = letta_agent_id

        # Cache for expensive lookups
        self._notification_cache: Dict[str, Any] = {}
        self._cache_time: Optional[datetime] = None
        self._cache_ttl_seconds = 60  # Cache notifications for 1 minute

    def _get_bsky_api(self):
        """Lazy initialization of Bluesky API."""
        if self._bsky_api is None:
            try:
                from config_loader import get_bluesky_config
                from flow.bsky_api import BskyApi

                bsky_cfg = get_bluesky_config()
                self._bsky_api = BskyApi(
                    username=bsky_cfg.get("username"),
                    password=bsky_cfg.get("password"),
                    pds_uri=bsky_cfg.get("pds_uri"),
                )
            except Exception as e:
                logger.warning(f"Failed to initialize Bluesky API: {e}")
                return None
        return self._bsky_api

    def _get_letta_client(self):
        """Lazy initialization of Letta client."""
        if self._letta_client is None:
            try:
                from config_loader import get_letta_config
                from letta_client import Letta

                letta_cfg = get_letta_config()
                params = {
                    "api_key": letta_cfg["api_key"],
                    "timeout": letta_cfg.get("timeout", 600),
                }
                if letta_cfg.get("base_url"):
                    params["base_url"] = letta_cfg["base_url"]
                self._letta_client = Letta(**params)
                self._letta_agent_id = letta_cfg["agent_id"]
            except Exception as e:
                logger.warning(f"Failed to initialize Letta client: {e}")
                return None
        return self._letta_client

    def _load_agent_state(self) -> Dict[str, Any]:
        """Load agent state from disk."""
        if not self.agent_state_path.exists():
            return {}
        try:
            return json.loads(self.agent_state_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Failed to load agent state: {e}")
            return {}

    def _is_cache_valid(self) -> bool:
        """Check if the notification cache is still valid."""
        if self._cache_time is None:
            return False
        elapsed = (datetime.now(timezone.utc) - self._cache_time).total_seconds()
        return elapsed < self._cache_ttl_seconds

    def get_pending_notifications(self) -> Dict[str, Any]:
        """Get count of pending notifications by platform and type.

        Returns:
            Dict with platform-tagged notifications:
            {
                'bluesky': {'mentions': 1, 'replies': 5, ...},
                'moltbook': {'comments': 2, ...},
                'total': 8
            }
        """
        # Check cache first
        if self._is_cache_valid() and "notifications" in self._notification_cache:
            return self._notification_cache["notifications"]

        pending = {
            "bluesky": {"mentions": 0, "replies": 0, "likes": 0, "follows": 0, "other": 0},
            "moltbook": {"comments": 0, "mentions": 0, "other": 0},
            "total": 0,
            "_note": "Reply on the SAME platform where notification originated",
        }

        # Get Bluesky notifications
        bsky = self._get_bsky_api()
        if bsky:
            try:
                notifications = bsky.list_notifications(limit=50)
                # Load processed notifications from the real database
                try:
                    from notification_db import NotificationDB
                    db = NotificationDB()
                    processed = db.get_all_processed_uris()
                    db.close()
                except Exception:
                    processed = set()

                for notif in notifications:
                    uri = notif.get("uri", "")
                    if uri in processed:
                        continue
                    reason = notif.get("reason", "other")
                    if reason == "mention":
                        pending["bluesky"]["mentions"] += 1
                    elif reason == "reply":
                        pending["bluesky"]["replies"] += 1
                    elif reason == "like":
                        pending["bluesky"]["likes"] += 1
                    elif reason == "follow":
                        pending["bluesky"]["follows"] += 1
                    else:
                        pending["bluesky"]["other"] += 1
            except Exception as e:
                logger.warning(f"Failed to get Bluesky notifications: {e}")

        # TODO: Add Moltbook pending items when API supports it
        # For now, Moltbook notifications are checked via moltbook_get_notifications tool

        # Calculate total
        pending["total"] = (
            sum(pending["bluesky"].values()) +
            sum(pending["moltbook"].values())
        )

        # Update cache
        self._notification_cache["notifications"] = pending
        self._cache_time = datetime.now(timezone.utc)

        return pending

    def get_context_usage(self) -> float:
        """Get context window usage as a fraction (0.0-1.0).

        This is a lightweight check - for detailed breakdown,
        the agent should call view_context_budget directly.
        """
        client = self._get_letta_client()
        if not client or not self._letta_agent_id:
            return 0.0

        try:
            agent = client.agents.retrieve(agent_id=self._letta_agent_id)
            # Estimate usage based on message count and core memory
            # This is approximate - actual context usage depends on token counts
            messages = getattr(agent, "message_ids", []) or []
            # Rough estimate: assume average 500 tokens per message
            estimated_tokens = len(messages) * 500
            # Assume 128k context window
            max_tokens = 128000
            return min(1.0, estimated_tokens / max_tokens)
        except Exception as e:
            logger.warning(f"Failed to get context usage: {e}")
            return 0.0

    def get_time_since_last_action(self) -> float:
        """Get seconds since last agent action."""
        state = self._load_agent_state()
        last_commit = state.get("last_commit_at")
        if not last_commit:
            return float('inf')

        try:
            then = datetime.fromisoformat(last_commit)
            now = datetime.now(timezone.utc)
            return (now - then).total_seconds()
        except Exception:
            return float('inf')

    def get_error_count_last_hour(self) -> int:
        """Get number of errors in the last hour from telemetry."""
        if not self.telemetry_path.exists():
            return 0

        error_count = 0
        now = datetime.now(timezone.utc)
        one_hour_ago = (now.timestamp() - 3600)

        try:
            with open(self.telemetry_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        event = json.loads(line.strip())
                        timestamp = event.get("timestamp")
                        if timestamp:
                            event_time = datetime.fromisoformat(timestamp).timestamp()
                            if event_time < one_hour_ago:
                                continue
                        # Check for error indicators
                        if event.get("abort_reason") in [
                            "commit_failed",
                            "preflight_failed",
                            "error",
                        ]:
                            error_count += 1
                    except (json.JSONDecodeError, KeyError):
                        continue
        except Exception as e:
            logger.warning(f"Failed to read telemetry: {e}")

        return error_count

    def is_human_active(self) -> bool:
        """Check if human is currently active.

        For now, this always returns False. Could be enhanced to:
        - Check for recent human messages
        - Integrate with sleep status
        - Check time of day
        """
        state = self._load_agent_state()
        # Check quiet hours state if available
        quiet_hours = state.get("quiet_hours")
        if quiet_hours:
            return False

        # Could add more sophisticated detection here
        return False

    def get_output_stats(self) -> Dict[str, float]:
        """Get recent output statistics for drift detection.

        Returns average response length and other metrics from
        recent telemetry.
        """
        if not self.telemetry_path.exists():
            return {}

        lengths = []
        now = datetime.now(timezone.utc)
        six_hours_ago = now.timestamp() - (6 * 3600)

        try:
            with open(self.telemetry_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        event = json.loads(line.strip())
                        timestamp = event.get("timestamp")
                        if timestamp:
                            event_time = datetime.fromisoformat(timestamp).timestamp()
                            if event_time < six_hours_ago:
                                continue
                        # Try to get response length from commit results
                        commit = event.get("commit_result", {})
                        if commit and commit.get("success"):
                            # This is approximate - actual length would need
                            # to come from the draft text
                            lengths.append(100)  # Placeholder
                    except (json.JSONDecodeError, KeyError):
                        continue
        except Exception as e:
            logger.warning(f"Failed to read telemetry for stats: {e}")

        if not lengths:
            return {}

        return {
            "avg_length": sum(lengths) / len(lengths),
            "baseline_length": 100,  # Placeholder baseline
            "sample_count": len(lengths),
        }


class MinimalStateProvider(ExternalStateProvider):
    """Minimal state provider for testing or standalone use.

    Returns neutral values that don't boost any signals.
    """

    def get_pending_notifications(self) -> Dict[str, int]:
        return {}

    def get_context_usage(self) -> float:
        return 0.0

    def get_time_since_last_action(self) -> float:
        return 3600  # 1 hour - neutral

    def get_error_count_last_hour(self) -> int:
        return 0

    def is_human_active(self) -> bool:
        return False

    def get_output_stats(self) -> Dict[str, float]:
        return {}
